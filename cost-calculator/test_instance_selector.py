import os
import unittest
from instance_selector import (
    make_instance_selector,
    cheapest_custom_instance,
)

scriptdir = os.path.dirname(os.path.realpath(__file__))
datadir = os.path.join(scriptdir, 'instance-data')


class TestInstanceSelector(unittest.TestCase):
    def assert_matches(self, cpu, memory, gpu, expected):
        inst_type, _ = self.instance_selector.get_cheapest_instance(cpu, memory, gpu)
        msg = f'{self.instance_selector.cloud}: {cpu}, {memory}, {gpu} != {expected}, got {inst_type}'
        self.assertEqual(inst_type, expected, msg)

    def run_instance_test(self, cloud, region, cases):
        self.instance_selector = make_instance_selector(datadir, cloud, region)
        for case in cases:
            self.assert_matches(*case)

    def test_gce(self):
        cases = [
            (0, 3.75, '1', 'n1-standard-1'),
            (0, 3.75, '1 nvidia-tesla-p100', 'n1-standard-1'),
            (0.5, 1.7, '', 'g1-small'),
            (2, 1, '', 'e2-micro'),
            (1, 3.75, '', 'e2-custom-1-3840'),
            (48, 180, '', 'n2-standard-48'),
            (32, 15, '', 'n2-custom-32-16384'),

        ]
        self.run_instance_test('gce', 'us-west1-a', cases)

    def test_aws(self):
        cases = [
            (0, 0, '1', 'p2.xlarge'),
            (32, 15, '0', 'c5.9xlarge'),
            (48, 180, '', 'm5.12xlarge'),
        ]
        self.run_instance_test('aws', 'us-east-1', cases)

    # def test_azure(self):
    #     cases = [
    #         (0, 3.75, '1', 'n1-standard-1'),
    #     ]
    #     self.run_instance_test('azure', 'East US 2', cases)

    def test_cheapest_custom_instance(self):
        custom_instance_data = {
            'baseMemoryUnit':       0.25,
            'possibleNumberOfCPUs': [1.0, 2.0, 4.0, 6.0, 8.0],
            'minimumMemoryPerCPU':  0.5,
            'maximumMemoryPerCPU':  4.0,
            'pricePerCPU':          0.2,
            'pricePerGBOfMemory':   0.1,
        }
        cases = [
            (6, 3, 6*0.2 + 3*0.1, 6, 3),
            (6, 2, 3*0.1 + 6*0.2, 6, 3),
            (8.5, 2.0, None, None, None),
            (4, 32.5, None, None, None),
            (4, 20, 20*0.1 + 6*0.2, 6, 20),
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


if __name__ == '__main__':
    unittest.main()
