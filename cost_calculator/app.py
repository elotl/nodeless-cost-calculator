import logging
import os
import sys

import attr
from kubernetes import client, config
from kubernetes.utils import parse_quantity
from flask import Flask, jsonify, request
import flask

from cost_calculator.instance_selector import make_instance_selector

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
WEEK = 'week'
MONTH = 'month'
YEAR = 'year'

app = Flask(__name__)


def k8s_container_resource_requirements(container):
    try:
        max_cpu = 0
        max_memory = 0
        if not container.resources:
            return max_cpu, max_memory
        limits = container.resources.limits
        if limits and limits.get('cpu'):
            cpu = parse_quantity(limits['cpu'])
            max_cpu = cpu
        if limits and limits.get('memory'):
            memory = parse_quantity(limits['memory'])
            max_memory = memory
        requests = container.resources.requests
        if requests and requests.get('cpu'):
            cpu = parse_quantity(requests['cpu'])
            max_cpu = max(cpu, max_cpu)
        if requests and requests.get('memory'):
            memory = parse_quantity(requests['memory'])
            max_memory = max(memory, max_memory)
        return max_cpu, max_memory
    except Exception:
        logger.exception('Error getting resource requirements for container')


def k8s_pod_resource_requirements(pod):
    max_cpu = 0
    max_memory = 0
    if pod.spec.init_containers:
        for container in pod.spec.init_containers:
            cpu, memory = k8s_container_resource_requirements(container)
            max_cpu = max(cpu, max_cpu)
            max_memory = max(memory, max_memory)
    sum_cpu = 0
    sum_memory = 0
    if pod.spec.containers:
        for container in pod.spec.containers:
            cpu, memory = k8s_container_resource_requirements(container)
            sum_cpu += cpu
            sum_memory += memory
    max_cpu = float(max(sum_cpu, max_cpu))
    max_memory = float(max(sum_memory, max_memory))
    max_memory = max_memory / (1024.0 * 1024.0 * 1024.0)
    return max_cpu, max_memory, ''


@attr.s
class Pod:
    '''Our representation of a pod, simpler to deal with and less
    error prone than using k8s pods
    '''
    namespace = attr.ib()
    name = attr.ib()
    cpu = attr.ib()
    memory = attr.ib()
    gpu_spec = attr.ib()
    instance_type = attr.ib(default='')
    cost = attr.ib(default=0.0)

    @classmethod
    def from_k8s(cls, kpod):
        namespace = kpod.metadata.namespace
        name = kpod.metadata.name
        try:
            cpu, memory, gpu_spec = k8s_pod_resource_requirements(kpod)
        except ValueError:
            # todo
            raise

        return cls(namespace, name, cpu, memory, gpu_spec)

    def find_pod_by_name(self, pod_name):
        # todo
        if self.name == pod_name:
            return {
                'namespace': self.namespace,
                'name': self.name,
                'cpu': self.cpu,
                'memory': self.memory,
                'gpu_spec': self.gpu_spec,
                'instance_type': self.instance_type,
                'cost': self.cost
            }

    def serialize(self):
        return {
            'namespace': self.namespace,
            'name': self.name,
            'cpu': self.cpu,
            'memory': self.memory,
            'gpu_spec': self.gpu_spec,
            'instance_type': self.instance_type,
            'cost': self.cost
        }

    def __str__(self):
        return f'<{self.namespace}:{self.name}, {self.instance_type}, {self.cost}>'

    def __repr__(self):
        return str(self)


@attr.s
class Node:
    '''Our representation of a kubernetes worker node'''
    name = attr.ib()
    nodegroup = attr.ib()
    cpu = attr.ib()
    memory = attr.ib()
    gpu_spec = attr.ib()
    instance_type = attr.ib(default='')
    cost = attr.ib(default=0.0)

    @classmethod
    def from_k8s(cls, node):
        name = node.metadata.name
        if cloud_provider == 'gce':
            nodegroup = node.metadata.labels.get(
                'alpha.eksctl.io/nodegroup-name', '')
        else:
            nodegroup = node.metadata.labels.get(
                'eks.amazonaws.com/nodegroup', '')
            if not nodegroup:
                nodegroup = node.metadata.labels.get(
                    'alpha.eksctl.io/nodegroup-name', '')
        instance_type = node.metadata.labels.get(
            'beta.kubernetes.io/instance-type', '')
        return cls(name, nodegroup, '', '', '', instance_type, 0.0)


@attr.s
class CostCalculator:
    '''
    This is the central hub of our application it takes care of
    querying for pods, and using the InstanceSelector to create a cost
    calculation.

    This class creates an attribute: cost_summary that holds
    a dict[namespace][name] of pods with instance_type and cost
    that'll help users drill down into the requested pod resources
    '''
    core_client = attr.ib()
    instance_selector = attr.ib()
    cost_summary = attr.ib(default=attr.Factory(dict))
    no_resource_spec = attr.ib(default=False)
    hours_in_week = 168
    hours_in_month = 730
    hours_in_year = 8760
    # def __attrs_post_init__(self):
    #     if self.namespace:
    #         self.pod_lister_func = functools.partial(
    #             self.namespace)
    #     else:
    #         self.pod_lister_func = functools.partial(

    def calculate_cluster_cost(self, namespace):
        pods = self.get_pods(namespace)
        for pod in pods:
            pod.instance_type, pod.cost = self.instance_selector.get_cheapest_instance(pod.cpu, pod.memory, pod.gpu_spec)
            if pod.cpu == 0 and pod.memory == 0:
                pod.no_resource_spec = True
        return pods

    def calculate_current_cluster_cost(self):
        # todo
        # calculate the cost of the cluster currently with nodes
        nodes = self.get_nodes()
        for node in nodes:
            node_spec = self.instance_selector.spec_for_inst_type(node.instance_type)
            if not node_spec:
                continue
            node.cpu = node_spec['cpu']
            node.memory = node_spec['memory']
            node.cost = node_spec['price']
            node.gpu_spec = node_spec['gpu']
        return nodes

    def calculate_nodeless_cost(self, namespace, num_hours, pod_name=''):
        if namespace == 'all':
            namespace = ''
        pod_list = self.calculate_cluster_cost(namespace)
        if pod_name != '':
            for pod in pod_list:
                if pod.name != pod_name:
                    # todo -- no such named pod exists
                    continue
                else:
                    return round(pod.cost * num_hours, 3)
        else:
            # get monthly cost for all pods in aggregate
            cost = 0.0
            for pod in pod_list:
                # todo remove debug statement
                print(pod.name, pod.cost)
                cost += pod.cost
            return round(cost * num_hours, 3)

    def pod_costs(self, namespace):
        pods = self.calculate_cluster_cost(namespace)
        return jsonify(costs=[pod.cost * 100 for pod in pods])

    def get_pods(self, namespace):
        if namespace == '':
            kpods = self.core_client.list_pod_for_all_namespaces()
        else:
            kpods = self.core_client.list_namespaced_pod(namespace)
        # todo, remove debugging
        print('num pods', len(kpods.items))
        return [Pod.from_k8s(kpod) for kpod in kpods.items]

    def get_nodes(self):
        nodes = self.core_client.list_node()
        print('num worker nodes', len(nodes.items))
        return [Node.from_k8s(node) for node in nodes.items]


def make_instance_calculator(kubeconfig, cloud_provider, region):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        config.load_incluster_config()
    core_client = client.CoreV1Api()
    datadir = 'instance-data'
    instance_selector = make_instance_selector(datadir, cloud_provider, region)
    return CostCalculator(core_client, instance_selector)


@app.route('/', methods=['GET', 'POST'])
def cost_summary():
    # TODO clean this up!!!
    global instance_calculator
    namespace = ''
    data = {
        'pod_cost': 0,
        'pod_count': 0,
        'pod_total_cpu': 0,
        'pod_total_memory': 0,
        'node_cost': 0,
        'node_count': 0,
        'node_total_cpu': 0,
        'node_total_memory': 0,
        'savings': 0,
        'savings_percentage': 0,
        'selected_timeframe': '',
        'timeframes': [WEEK, MONTH, YEAR]
    }

    pods = instance_calculator.calculate_cluster_cost(namespace)
    nodes = instance_calculator.calculate_current_cluster_cost()
    # default to month for time
    period = MONTH
    timeframe = total_pods_cost(period)
    if request.method == 'POST':
        period =  request.form.get('timeframes')
        timeframe = total_pods_cost(period)
    data['selected_timeframe'] = period
    for node in nodes:
        if not node.cost:
            # todo: flash an error at the top of the screen
            pass
        else:
            data['node_cost'] += node.cost
            data['node_total_cpu'] += node.cpu
            data['node_total_memory'] += node.memory
    for pod in pods:
        data['pod_cost'] += pod.cost
        data['pod_total_cpu'] += pod.cpu
        data['pod_total_memory'] += pod.memory
    data['node_cost'] = round(data['node_cost'] * timeframe, 2)
    data['pod_cost'] = round(data['pod_cost'] * timeframe, 2)
    data['node_count'] = len(nodes)
    data['pod_count'] = len(pods)
    data['savings'] = round(data['node_cost'] - data['pod_cost'], 2)
    data['savings_percentage'] = round(
        (data['savings'] / data['node_cost']) * 100, 2)
    return flask.render_template('comparison.html', data=data)


@app.route('/node_cost', methods=['GET', 'POST'])
def node_cost():
    global instance_calculator
    data = {
        'cost': 0,
        'nodes': [],
        'node_count': 0,
        'selected_timeframe': '',
        'timeframes': [WEEK, MONTH, YEAR]
    }
    nodes = instance_calculator.calculate_current_cluster_cost()

    period = MONTH
    timeframe = total_pods_cost(period)
    if request.method == 'POST':
        period =  request.form.get('timeframes')
        if period:
            timeframe = total_pods_cost(period)
    data['selected_timeframe'] = period

    for node in nodes:
        print(node)
        data['cost'] += node.cost
    data['cost'] = round(data['cost'] * timeframe, 2)
    data['nodes'] = nodes
    data['node_count'] = len(nodes)

    # get the pod selected
    return flask.render_template('node_cost.html', data=data)


@app.route('/nodeless_forcast', methods=['GET', 'POST'])
def forcast_summary():
    global instance_calculator
    namespace = ''
    data = {
        'cost': 0,
        'pods': [],
        'pod_count': 0,
        'selected_namespace': '',
        'namespaces': ['all'],
        'selected_timeframe': '',
        'timeframes': [WEEK, MONTH, YEAR]
    }
    pods = instance_calculator.calculate_cluster_cost(namespace)
    for pod in pods:
        if pod.namespace not in data['namespaces']:
            data['namespaces'].append(pod.namespace)

    period = MONTH
    timeframe = total_pods_cost(period)
    if request.method == 'POST':
        namespace = request.form.get('namespaces')
        if not namespace:
            namespace = 'all'
        else:
            data['selected_namespace'] = namespace
        for pod in pods:
            if pod.namespace != namespace and namespace != 'all':
                continue
            data['pods'].append(pod)
        period =  request.form.get('timeframes')
        if period:
            timeframe = total_pods_cost(period)
    data['selected_timeframe'] = period

    if request.method == 'GET':
        data['pods'] = pods

    print('namespace: ', namespace)
    data['cost'] = instance_calculator.calculate_nodeless_cost(
        namespace, timeframe)
    data['pod_count'] = len(data['pods'])

    return flask.render_template('cost_summary.html', data=data)


@app.route('/api/cost/pods/<namespace>', methods=['GET'])
def calc(namespace):
    global instance_calculator
    if namespace == 'all':
        namespace = ''
    return instance_calculator.pod_costs(namespace)


def total_pods_cost(timeframe):
    global instance_calculator
    namespace = ''
    # todo -- cleanup hardcoded time values
    if timeframe == WEEK:
        timeframe = instance_calculator.hours_in_week
    elif timeframe == MONTH:
        timeframe = instance_calculator.hours_in_month
    elif timeframe == YEAR:
        timeframe = instance_calculator.hours_in_year
    else:
        # todo -- add catch for no such timeframe
        return
    return timeframe


kubeconfig = os.getenv('KUBECONFIG', '')
cloud_provider = os.getenv('CLOUD_PROVIDER')
if not cloud_provider:
    logger.fatal(
        'CLOUD_PROVIDER environment variable is required. '
        'Please restart this pod with a CLOUD_PROVIDER '
        'environment variable set (one of: aws, gce, azure)')
    sys.exit(1)
region = os.getenv('REGION')
if not region:
    logger.fatal(
        'REGION environment variable is required. '
        'Please restart this pod with a REGION environment variable set.')
    sys.exit(1)
instance_calculator = make_instance_calculator(
    kubeconfig, cloud_provider, region)


#@app.route('/api/cost/pod/<pod_name>', methods=['GET'])
#def pod_cost_by_name(pod_name):
#    global instance_calculator
#    namespace = ''
#    pod_cost = instance_calculator.calculate_monthly_cost(namespace, pod_name)
#    return jsonify(pod_cost)
#
#
#@app.route('/api/cost/namespace/<namespace>', methods=['GET'])
#def pod_cost_by_namespace(namespace):
#    global instance_calculator
#    pod_cost = instance_calculator.calculate_nodeless_cost(namespace)
#    return jsonify(pod_cost)
#
#
#@app.route('/api/cost/<timeframe>', methods=['GET'])
#def total_pods_cost(timeframe):
#    global instance_calculator
#    namespace = ''
#    # todo -- cleanup hardcoded time values
#    if timeframe == WEEK:
#        timeframe = instance_calculator.hours_in_week
#    elif timeframe == MONTH:
#        timeframe = instance_calculator.hours_in_month
#    elif timeframe == YEAR:
#        timeframe = instance_calculator.hours_in_year
#    else:
#        # todo -- add catch for no such timeframe
#        return
#
#    pod_cost = instance_calculator.calculate_nodeless_cost(namespace, timeframe)
#    return jsonify(pod_cost)
#
#
#
#@app.route('/api/pods', methods=['GET'])
#def calculate():
#    pod_list = instance_calculator.calculate_cluster_cost('')
#    return jsonify(pods=[pod.serialize() for pod in pod_list])
