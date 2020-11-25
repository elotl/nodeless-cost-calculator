import json
import logging
import os
import sys
from typing import Dict

import attr
from kubernetes import client, config
from kubernetes.client import V1Pod, V1ObjectMeta, V1PodSpec, V1Container, V1ResourceRequirements, V1Node
from kubernetes.utils import parse_quantity
from flask import Flask, jsonify, request, flash
import flask

from cost_calculator.instance_selector import make_instance_selector

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
WEEK = 'week'
MONTH = 'month'
YEAR = 'year'
KIP_NODE_LABEL_KEY = 'type'
KIP_NODE_LABEL_VALUE = 'virtual-kubelet'

app = Flask(__name__)
app.secret_key = os.urandom(24)


def k8s_container_resource_requirements(container) -> Dict[str, int]:
    """
    returns dict in format:
     {"req_cpu": 1, "req_mem": 1, "lim_cpu": 2, "lim_mem": 2}
    """
    try:
        max_cpu = 0
        max_memory = 0
        if not container.resources:
            return {
                "req_cpu": max_cpu,
                "req_mem": max_memory,
                "lim_cpu": max_cpu,
                "lim_mem": max_memory
            }
        limits = container.resources.limits
        max_lim_cpu = 0
        max_lim_mem = 0
        if limits and limits.get('cpu'):
            cpu = parse_quantity(limits['cpu'])
            max_lim_cpu = cpu
        if limits and limits.get('memory'):
            memory = parse_quantity(limits['memory'])
            max_lim_mem = memory
        requests = container.resources.requests
        max_req_cpu = 0
        max_req_mem = 0
        if requests and requests.get('cpu'):
            cpu = parse_quantity(requests['cpu'])
            max_req_cpu = max(cpu, max_cpu)
        if requests and requests.get('memory'):
            memory = parse_quantity(requests['memory'])
            max_req_mem = max(memory, max_memory)
        return {
            "req_cpu": max_req_cpu,
            "req_mem": max_req_mem,
            "lim_cpu": max_lim_cpu,
            "lim_mem": max_lim_mem
        }
    except Exception:
        logger.exception('Error getting resource requirements for container')


def k8s_pod_resource_requirements(pod):
    max_req_cpu = 0
    max_lim_cpu = 0
    max_req_memory = 0
    max_lim_memory = 0
    if pod.spec.init_containers:
        for container in pod.spec.init_containers:
            resources = k8s_container_resource_requirements(container)
            req_cpu, req_mem = resources['req_cpu'], resources['req_mem']
            lim_cpu, lim_mem = resources['lim_cpu'], resources['lim_mem']
            max_req_cpu = max(req_cpu, max_req_cpu)
            max_lim_cpu = max(lim_cpu, max_lim_cpu)
            max_req_memory = max(req_mem, max_req_memory)
            max_lim_memory = max(lim_mem, max_lim_memory)
    sum_req_cpu = 0
    sum_lim_cpu = 0
    sum_req_memory = 0
    sum_lim_memory = 0
    if pod.spec.containers:
        for container in pod.spec.containers:
            resources = k8s_container_resource_requirements(container)
            sum_lim_cpu += resources['lim_cpu']
            sum_lim_memory += resources['lim_mem']
            sum_req_cpu += resources['req_cpu']
            sum_req_memory += resources['req_mem']
    max_req_cpu = float(max(sum_req_cpu, max_req_cpu))
    max_lim_cpu = float(max(sum_lim_cpu, max_lim_cpu))
    max_req_memory = float(max(sum_req_memory, max_req_memory))
    max_req_memory = max_req_memory / (1024.0 * 1024.0 * 1024.0)
    max_lim_memory = float(max(sum_lim_memory, max_lim_memory))
    max_lim_memory = max_lim_memory / (1024.0 * 1024.0 * 1024.0)
    return max_req_cpu, max_req_memory, max_lim_cpu, max_lim_memory, ''


@attr.s
class Pod:
    '''Our representation of a pod, simpler to deal with and less
    error prone than using k8s pods
    '''
    namespace = attr.ib()
    name = attr.ib()
    req_cpu = attr.ib()
    req_memory = attr.ib()
    lim_cpu = attr.ib()
    lim_memory = attr.ib()
    gpu_spec = attr.ib()
    instance_type = attr.ib(default='')
    cost = attr.ib(default=0.0)
    spot_price = attr.ib(default=0.0)

    @classmethod
    def from_k8s(cls, kpod):
        namespace = kpod.metadata.namespace
        name = kpod.metadata.name
        try:
            req_cpu, req_memory, lim_cpu, lim_memory, gpu_spec = k8s_pod_resource_requirements(kpod)
        except ValueError:
            logger.exception('error getting resource requirements for container')
            raise

        return cls(
            namespace=namespace,
            name=name,
            req_cpu=req_cpu,
            req_memory=req_memory,
            lim_cpu=lim_cpu,
            lim_memory=lim_memory,
            gpu_spec=gpu_spec
        )

    @classmethod
    def from_file(cls, pod_dict):
        """
        expects input in format:
          {
            "name": "bonita-webapp-0",
            "namespace": "default",
            "containers": {
              "limits": {
                "memory": "24Gi"
              },
              "requests": {
                "cpu": "3",
                "memory": "12Gi"
              }
            },
            "initContainers": null
          },
        """
        containers = pod_dict['containers']
        if containers is not None:
            c_limits = containers.get('limits')
            c_requests = containers.get('requests')
        else:
            c_limits, c_requests = {}, {}

        init_containers = pod_dict['initContainers']
        if init_containers is not None:
            ic_limits = containers.get('limits')
            ic_requests = containers.get('requests')
        else:
            ic_limits, ic_requests = {}, {}
        pod = V1Pod(
            metadata=V1ObjectMeta(
                name=pod_dict['name'],
                namespace=pod_dict['namespace']
            ),
            spec=V1PodSpec(
                containers=[
                    V1Container(
                        name='1',
                        resources=V1ResourceRequirements(
                            limits=c_limits,
                            requests=c_requests
                        )
                    )
                ],
                init_containers=[
                    V1Container(
                        name='1',
                        resources=V1ResourceRequirements(
                            limits=ic_limits,
                            requests=ic_requests
                        ))
                ]
            )
        )
        return cls.from_k8s(pod)

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
        instance_type = node.metadata.labels.get(
            'beta.kubernetes.io/instance-type', '')
        if not instance_type:
            instance_type = node.metadata.labels.get(
                'kubernetes.io/instance-type', '')
        if cloud_provider == 'gce':
            nodegroup = node.metadata.labels.get(
                'alpha.eksctl.io/nodegroup-name', '')
        else:
            nodegroup = node.metadata.labels.get(
                'eks.amazonaws.com/nodegroup', '')
            if not nodegroup:
                nodegroup = node.metadata.labels.get(
                    'alpha.eksctl.io/nodegroup-name', '')
        return cls(name, nodegroup, '', '', '', instance_type, 0.0)

    @classmethod
    def from_file(cls, node_dict):
        node = V1Node(
            metadata=V1ObjectMeta(
                name=node_dict['name'],
                labels=node_dict['labels']
            ),
        )
        return cls.from_k8s(node)


@attr.s
class ClusterCost:
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
    from_file = attr.ib(default=False)
    file_data = attr.ib(default=None)
    hours_in_week = 168
    hours_in_month = 730
    hours_in_year = 8760

    def get_current_cluster_cost(self):
        if self.from_file:
            return []
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

    def get_nodeless_pods(self, namespace):
        pods = self.get_pods(namespace)
        for pod in pods:
            cpu = max(pod.lim_cpu, pod.req_cpu)
            memory = max(pod.lim_memory, pod.req_memory)
            pod.instance_type, pod.cost, pod.spot_price = self.instance_selector.get_cheapest_instance(cpu, memory,
                                                                                                       pod.gpu_spec)
            print(pod)
            if cpu == 0 and memory == 0:
                pod.no_resource_spec = True
        return pods

    def get_total_nodeless_cost(self, namespace, num_hours, pod_name='', cost_field='cost'):
        if namespace == 'all':
            namespace = ''
        pod_list = self.get_nodeless_pods(namespace)
        if pod_name != '':
            for pod in pod_list:
                if pod.name != pod_name:
                    continue
                else:
                    cost = getattr(pod, cost_field)
                    return round(cost * num_hours, 3)
        else:
            # get monthly cost for all pods in aggregate
            cost = 0.0
            for pod in pod_list:
                pod_cost = getattr(pod, cost_field)
                cost += pod_cost
            return round(cost * num_hours, 3)

    def pod_costs(self, namespace):
        pods = self.get_nodeless_pods(namespace)
        return jsonify(costs=[pod.cost * 100 for pod in pods])

    def get_pods(self, namespace):
        if self.from_file:
            return [Pod.from_file(pod_dict) for pod_dict in self.file_data['pods']]
        if namespace == '':
            kpods = self.core_client.list_pod_for_all_namespaces()
        else:
            kpods = self.core_client.list_namespaced_pod(namespace)
        return [Pod.from_k8s(kpod) for kpod in kpods.items]

    def get_nodes(self):
        if self.from_file:
            return [Node.from_file(node_dict) for node_dict in self.file_data['nodes']]
        nodes = self.core_client.list_node()
        filtered_nodes = self._filter_kip_nodes(nodes)
        print('num worker nodes', len(filtered_nodes))
        return [Node.from_k8s(node) for node in filtered_nodes]

    def _filter_kip_nodes(self, nodes):
        filtered_nodes = [
            node for node in nodes.items
            if not node.metadata.labels.get(KIP_NODE_LABEL_KEY, '') == KIP_NODE_LABEL_VALUE
        ]
        return filtered_nodes


def make_cluster_cost_calculator(kubeconfig, cloud_provider, region, from_file=False, file_path=''):
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    datadir = os.path.join(scriptdir, 'instance-data')
    instance_selector = make_instance_selector(datadir, cloud_provider, region)
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        config.load_incluster_config()
    if from_file:
        data = _load_json_data(file_path)
        return ClusterCost(None, instance_selector, from_file=True, file_data=data)
    core_client = client.CoreV1Api()
    return ClusterCost(core_client, instance_selector)


def _load_json_data(file_path):
    with open(file_path, 'r') as jfile:
        data = json.load(jfile)
    return data


@app.route('/', methods=['GET', 'POST'])
def cost_summary():
    # TODO clean this up!!!
    namespace = ''
    data = {
        'pod_cost': 0,
        'pod_spot_cost': 0,
        'pod_count': 0,
        'pod_total_cpu': 0,
        'pod_total_memory': 0,
        'node_cost': 0,
        'node_count': 0,
        'node_total_cpu': 0,
        'node_total_memory': 0,
        'savings': 0,
        'savings_for_spot': 0,
        'savings_percentage': 0,
        'savings_spot_percentage': 0,
        'selected_timeframe': '',
        'timeframes': [WEEK, MONTH, YEAR]
    }

    pods = cluster_cost_calculator.get_nodeless_pods(namespace)
    nodes = cluster_cost_calculator.get_current_cluster_cost()
    # default to month for time
    period = MONTH
    timeframe = total_pods_cost(period)
    if request.method == 'POST':
        period = request.form.get('timeframes')
        timeframe = total_pods_cost(period)
    data['selected_timeframe'] = period
    invalid_nodes = []
    for node in nodes:
        if not node.cost:
            invalid_nodes.append(node.name)
        else:
            data['node_cost'] += node.cost
            data['node_total_cpu'] += node.cpu
            data['node_total_memory'] += node.memory
    for pod in pods:
        data['pod_cost'] += pod.cost
        data['pod_spot_cost'] += pod.spot_price
        data['pod_total_cpu'] += max(pod.req_cpu, pod.lim_cpu)
        data['pod_total_memory'] += max(pod.req_memory, pod.lim_memory)
    if invalid_nodes:
        flash('Error: cost summary is likely incorrect. Could not calculate '
              'node cost for the following nodes: {}'.format(
            ', '.join(invalid_nodes)))
    data['node_cost'] = round(data['node_cost'] * timeframe, 2)
    data['pod_cost'] = round(data['pod_cost'] * timeframe, 2)
    data['pod_spot_cost'] = round(data['pod_spot_cost'] * timeframe, 2)
    data['node_count'] = len(nodes)
    data['pod_count'] = len(pods)
    data['savings'] = round(data['node_cost'] - data['pod_cost'], 2)
    data['savings_for_spot'] = round(data['node_cost'] - data['pod_spot_cost'], 2)
    if data['node_cost'] != 0:
        data['savings_percentage'] = round((data['savings'] / data['node_cost']) * 100, 2)
        data['savings_spot_percentage'] = round((data['savings_for_spot'] / data['node_cost']) * 100, 2)
    return flask.render_template('comparison.html', data=data)


@app.route('/node_cost', methods=['GET', 'POST'])
def node_cost():
    data = {
        'cost': 0,
        'nodes': [],
        'node_count': 0,
        'selected_timeframe': '',
        'timeframes': [WEEK, MONTH, YEAR]
    }
    nodes = cluster_cost_calculator.get_current_cluster_cost()

    period = MONTH
    timeframe = total_pods_cost(period)
    if request.method == 'POST':
        period = request.form.get('timeframes')
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
    pods = cluster_cost_calculator.get_nodeless_pods(namespace)
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
        period = request.form.get('timeframes')
        if period:
            timeframe = total_pods_cost(period)
    data['selected_timeframe'] = period

    if request.method == 'GET':
        data['pods'] = pods

    print('namespace: ', namespace)
    data['cost'] = cluster_cost_calculator.get_total_nodeless_cost(
        namespace, timeframe
    )
    data['spot_cost'] = cluster_cost_calculator.get_total_nodeless_cost(
        namespace, timeframe, cost_field='spot_price'
    )
    data['pod_count'] = len(data['pods'])

    return flask.render_template('cost_summary.html', data=data)


@app.route('/api/cost/pods/<namespace>', methods=['GET'])
def calc(namespace):
    if namespace == 'all':
        namespace = ''
    return cluster_cost_calculator.pod_costs(namespace)


def total_pods_cost(timeframe):
    namespace = ''
    if timeframe == WEEK:
        timeframe = cluster_cost_calculator.hours_in_week
    elif timeframe == MONTH:
        timeframe = cluster_cost_calculator.hours_in_month
    elif timeframe == YEAR:
        timeframe = cluster_cost_calculator.hours_in_year
    else:
        flash('Error: Timeframe given is not valid. '
              'Given timeframe: {}'.format(timeframe))
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

from_file = False
if os.getenv('FROM_FILE', False):
    from_file = True
file_path = os.getenv('INPUT_FILE_PATH', '/app/input_data.json')

if not os.getenv('IS_TEST_SUITE', False):
    cluster_cost_calculator = make_cluster_cost_calculator(
        kubeconfig, cloud_provider, region, from_file=from_file, file_path=file_path
    )
