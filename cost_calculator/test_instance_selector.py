import os
import unittest
from unittest.mock import Mock, patch

from instance_selector import (
    make_instance_selector,
    cheapest_custom_instance,
    PriceGetter
)
from kubernetes.client.models import V1Node, V1NodeList, V1ObjectMeta, V1Pod, V1PodSpec, V1Container, \
    V1ResourceRequirements

os.environ['IS_TEST_SUITE'] = 'yes'
from cost_calculator.app import ClusterCost, KIP_NODE_LABEL_KEY, KIP_NODE_LABEL_VALUE, k8s_pod_resource_requirements

scriptdir = os.path.dirname(os.path.realpath(__file__))
datadir = os.path.join(scriptdir, 'instance-data')


class TestUtils(unittest.TestCase):
    def test_pod_resources(self):
        cases = [
            {
                "pod": V1Pod(
                    spec=V1PodSpec(
                        init_containers=[
                            V1Container(
                                name="1",
                                resources=V1ResourceRequirements(
                                    limits={},
                                    requests={}
                                )
                            )],
                        containers=[
                            V1Container(
                                name="1",
                                resources=V1ResourceRequirements(
                                    limits={},
                                    requests={}
                                )
                            ),
                            V1Container(
                                name="2",
                                resources=V1ResourceRequirements(
                                    limits={},
                                    requests={}
                                )
                            )
                        ]
                    )),
                # req_cpu, req_memory, lim_cpu, lim_memory, gpu_spec
                "expected": (0, 0, 0, 0, '')
            },
            {
                "pod": V1Pod(
                    spec=V1PodSpec(
                        init_containers=[
                            V1Container(
                                name="1",
                                resources=V1ResourceRequirements(
                                    limits={"cpu": "1", "memory": "512Mi"},
                                    requests={"cpu": "0.5", "memory": "256Mi"}
                                )
                            )],
                        containers=[
                            V1Container(
                                name="1",
                                resources=V1ResourceRequirements(
                                    limits={"cpu": "6", "memory": "6Gi"},
                                    requests={"cpu": "3", "memory": "0.5Gi"}
                                )
                            ),
                            V1Container(
                                name="2",
                                resources=V1ResourceRequirements(
                                    limits={"cpu": "2", "memory": "2Gi"},
                                    requests={"cpu": "1.5", "memory": "1Gi"}
                                )
                            )
                        ]
                    )),
                # req_cpu, req_memory, lim_cpu, lim_memory, gpu_spec
                "expected": (4.5, 1.5, 8.0, 8.0, '')
            }
        ]
        for case in cases:
            got = k8s_pod_resource_requirements(case['pod'])
            self.assertEqual(got, case['expected'])


class TestInstanceSelector(unittest.TestCase):
    def assert_matches(self, cpu, memory, gpu, expected):
        inst_type, _, _ = self.instance_selector.get_cheapest_instance(cpu, memory, gpu)
        msg = f'{self.instance_selector.cloud}: {cpu}, {memory}, {gpu} != expected {expected}, got {inst_type}'
        self.assertEqual(inst_type, expected, msg)

    def run_instance_test(self, cloud, region, cases):
        with patch('cost_calculator.instance_selector.redis.Redis.get') as mocked_get:
            mocked_get.return_value = b'{"onDemandPrice": 0.0252, "spotPrices": null}'
            self.instance_selector = make_instance_selector(datadir, cloud, region)
            for case in cases:
                self.assert_matches(*case)

    def test_price_for_gce_custom_instance(self):
        cases = [
            ('n1', 2, 3.75, 0.033174 * 2 + 0.004446 * 3.75),
            ('e2', 2, 4.0, 2 * 0.02289 + 4.0 * 0.003068),
        ]
        instance_selector = make_instance_selector(
            datadir, 'gce', 'us-west1-a')
        for family, cpu, gb_memory, expected_price in cases:
            price = instance_selector.price_for_gce_custom_instance(
                family, cpu, gb_memory)
            assert price is not None, 'Inst type should not be none'
            self.assertEqual(price, expected_price, 'price does not match expected price')

    def test_gce_spec_for_inst_type(self):
        cases = [
            ('custom-1-1024', 1, 1.0),
            ('custom-2-3840', 2, 3.75),
        ]
        instance_selector = make_instance_selector(
            datadir, 'gce', 'us-west1-a')
        for inst_type, cpu, gb_memory in cases:
            inst = instance_selector.spec_for_inst_type(inst_type)
            assert inst is not None, 'instance should not be nil'
            self.assertEqual(inst['cpu'], cpu)
            self.assertEqual(inst['memory'], gb_memory)

    def test_gce(self):
        cases = [
            (0, 3.75, '1', 'n1-standard-1'),
            (0, 3.75, '1 nvidia-tesla-p100', 'n1-standard-1'),
            (0.5, 1.7, '', 'g1-small'),
            (2, 1, '', 'e2-micro'),
            (1, 3.75, '', 'n1-standard-1'),
            (48, 180, '', 'n2-standard-48'),
            (32, 15, '', 'e2-highcpu-32'),
            (34, 16, '', 'n2-custom-34-17408'),
            (1.0, 0.5, '', 'n1-custom-1-1024'),

        ]
        self.run_instance_test('gce', 'us-west1-a', cases)

    def test_aws(self):
        cases = [
            (0, 0, '1', 'g4dn.xlarge'),
            (32, 15, '0', 'c6g.8xlarge'),
            (48, 180, '', 'm6g.12xlarge'),
        ]
        self.run_instance_test('aws', 'us-east-1', cases)

    def test_azure(self):
        cases = [
            (0, 0, '0', 'Standard_B1ls'),
        ]
        self.run_instance_test('azure', 'East US', cases)

    def test_cheapest_custom_instance(self):
        custom_instance_data = {
            'baseMemoryUnit': 0.25,
            'possibleNumberOfCPUs': [1.0, 2.0, 4.0, 6.0, 8.0],
            'minimumMemoryPerCPU': 0.5,
            'maximumMemoryPerCPU': 4.0,
            'pricePerCPU': 0.2,
            'pricePerGBOfMemory': 0.1,
        }
        cases = [
            (6, 3, 6 * 0.2 + 3 * 0.1, 6, 3),
            (6, 2, 3 * 0.1 + 6 * 0.2, 6, 3),
            (8.5, 2.0, None, None, None),
            (4, 32.5, None, None, None),
            (4, 20, 20 * 0.1 + 6 * 0.2, 6, 20),
        ]

        for case in cases:
            cpu_req = case[0]
            memory_req = case[1]
            expected_price = case[2]
            expected_cpu = case[3]
            expected_memory = case[4]
            cpu, memory, price = cheapest_custom_instance(
                custom_instance_data, cpu_req, memory_req)
            self.assertEqual(cpu, expected_cpu)
            self.assertEqual(memory, expected_memory)
            if cpu is not None:
                self.assertEqual(price, expected_price)


class TestClusterCost(unittest.TestCase):
    def test_get_nodes(self):
        # GIVEN
        core_mock = Mock()
        nodes_list = V1NodeList(
            items=[
                V1Node(
                    api_version='v1',
                    kind='Node',
                    metadata=V1ObjectMeta(
                        name='kip-node',
                        labels={KIP_NODE_LABEL_KEY: KIP_NODE_LABEL_VALUE}
                    )
                ),
                V1Node(
                    api_version='v1',
                    kind='Node',
                    metadata=V1ObjectMeta(
                        name='other-node',
                        labels={KIP_NODE_LABEL_KEY: 'other-value'}
                    )
                ),
                V1Node(
                    api_version='v1',
                    kind='Node',
                    metadata=V1ObjectMeta(
                        name='other-node-2',
                        labels={'other-key': 'other-value'}
                    )
                ),

            ])
        nodes_list.items = nodes_list.items
        core_mock.list_node.return_value = nodes_list
        cluster_cost = ClusterCost(core_mock, Mock())
        physical_nodes = ['other-node', 'other-node-2']

        # WHEN
        nodes = cluster_cost.get_nodes()

        # THEN
        for node in nodes:
            self.assertNotEqual(node.name, 'kip-node')
            self.assertIn(node.name, physical_nodes)


class RedisMock:
    def __init__(self, store):
        self.store = store

    def get(self, key):
        return self.store.get(key)


class TestPriceGetter(unittest.TestCase):
    def test_get_spot_price(self):
        cases = [
            {
                "store": {
                    "/banzaicloud.com/cloudinfo/providers/azure/regions/eastus/prices/Standard_B1ls": b'{"onDemandPrice": 0.0252, "spotPrice": null}'
                },
                "instanceType": "Standard_B1ls",
                "region": "East US",
                "expected_price": 0.0252
            },
            {
                "store": {
                    "/banzaicloud.com/cloudinfo/providers/azure/regions/eastus/prices/Standard_B1ls": b'{"onDemandPrice": 0.0252}'
                },
                "instanceType": "Standard_B1ls",
                "region": "East US",
                "expected_price": 0.0252
            },
            {
                "store": {
                    "/banzaicloud.com/cloudinfo/providers/azure/regions/eastus/prices/Standard_B1ls": b'{"onDemandPrice": 0.0252, "spotPrice": {"subregion1": 0.024, "subregion2": 0.0001}}'
                },
                "instanceType": "Standard_B1ls",
                "region": "East US",
                "expected_price": 0.0001
            },
        ]
        for case in cases:
            redis_client = RedisMock(store=case['store'])
            price_getter = PriceGetter(provider='azure', redis_client=redis_client)
            spot_price = price_getter.get_spot_price(instance_type=case['instanceType'], region=case['region'])
            self.assertEqual(spot_price, case['expected_price'])


if __name__ == '__main__':
    unittest.main()
