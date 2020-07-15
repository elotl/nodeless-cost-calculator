# todos
# list all pods in the namespace
# download cost files from s3 (for now, lets bundle them in the repo?)

# need to update InstanceSelector


from pprint import pprint
from collections import defaultdict
import logging
import functools

import attr
from kubernetes import client, config
from kubernetes.utils import parse_quantity
from flask import Flask
from flask_apscheduler import APScheduler
import flask

from cost_calculator.instance_selector import make_instance_selector


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
app = Flask(__name__)
# gets initialized at startup


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
    except Exception as e:
        import pdb; pdb.set_trace()
        print(e)


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
        except ValueError as e:
            # todo
            raise

        return cls(namespace, name, cpu, memory, gpu_spec)

    def __str__(self):
        return f'<{self.namespace}:{self.name}, {self.instance_type}, {self.cost}>'

    def __repr__(self):
        return str(self)


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

    def get_pods(self, namespace):
        if namespace == '':
            kpods = self.core_client.list_pod_for_all_namespaces()
        else:
            kpods = self.core_client.list_namespaced_pod(namespace)
        # todo, remove debugging
        print('num pods', len(kpods.items))
        return [Pod.from_k8s(kpod) for kpod in kpods.items]


def make_cost_calculator(kubeconfig, cloud_provider, region):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        config.load_incluster_config()
    core_client = client.CoreV1Api()
    datadir = 'instance-data'
    instance_selector = make_instance_selector(datadir, cloud_provider, region)
    return CostCalculator(core_client, instance_selector)


@app.route('/')
def cost_summary():
    global cost_calculator
    namespace = ''
    pods = cost_calculator.calculate_cluster_cost(namespace)
    return flask.render_template('cost_summary.html', pods=pods)


kubeconfig='/home/bcox/.kube/config'
cloud_provider = 'aws'
region = 'us-east-1'
cost_calculator = make_cost_calculator(
    kubeconfig, cloud_provider, region)
# cost_calculator.calculate_cluster_cost()

# class FlaskConfig:
#     pass

# flask_config = FlaskConfig()
# flask_config.JOBS = [
#     {
#         'id': 'job1',
#         'func': cost_calculator.calculate_cluster_cost,
#         # 'args': (),
#         'trigger': 'interval',
#         'seconds': 20,
#     }
# ]
# app.config.from_object(flask_config)
# scheduler = APScheduler()
# scheduler.init_app(app)
# scheduler.start()
# app.run()
