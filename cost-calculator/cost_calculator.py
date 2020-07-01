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
from flask import Flask
from flask_apscheduler import APScheduler
import flask

from instance_selector import make_instance_selector


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
app = Flask(__name__)
# gets initialized at startup
cost_calculator = None


def k8s_pod_resource_requirements(pod):
    return 0.0, 0.0, ''


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
        cpu, memory, gpu_spec = k8s_pod_resource_requirements(kpod)
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
    namespace = attr.ib()
    core_client = attr.ib()
    instance_selector = attr.ib()
    cost_summary = attr.ib(default=attr.Factory(dict))
    pod_lister_func = attr.ib(init=False)

    def __attrs_post_init__(self):
        if self.namespace:
            self.pod_lister_func = functools.partial(
                self.core_client.list_namespaced_pod,
                self.namespace)
        else:
            self.pod_lister_func = functools.partial(
                self.core_client.list_pod_for_all_namespaces)

    def calculate_cluster_cost(self):
        pods = self.get_pods()
        summary = defaultdict(dict)
        for pod in pods:
            pod.instance_type, pod.cost = self.instance_selector.get_instance_type(
                pod.cpu, pod.memory, pod.gpu_spec)
            summary['namespace']['name'] = pod
        self.cost_summary = summary

    def get_pods(self):
        kpods = self.pod_lister_func()
        return [Pod.from_k8s(kpod) for kpod in kpods]


def setup(kubeconfig, namespace, cloud_provider):
    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        config.load_incluster_config()
    core_client = client.CoreV1Api()
    instance_selector = make_instance_selector(cloud_provider)
    return CostCalculator(namespace, core_client, instance_selector)


@app.route('/')
def cost_summary():
    pods = []
    for ns_pods in cost_calculator.cost_summary.values():
        for pod in ns_pods.values():
            pods.append(pod)
    pprint(pods)
    return flask.render_template('cost_summary.html', pods=pods)


if __name__ == '__main__':
    global cost_calculator
    kubeconfig='/home/bcox/.kube/config'
    namespace = 'default'
    cloud_provider = 'aws'
    cost_calculator = setup(kubeconfig, namespace, cloud_provider)

    class Config:
        pass
    config = Config()
    config.JOBS = [
        {
            'id': 'job1',
            'func': cost_calculator.calculate_cluster_cost,
            # 'args': (),
            'trigger': 'interval',
            'seconds': 1,
        }
    ]
    app.config.from_object(config)
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()

    app.run()
