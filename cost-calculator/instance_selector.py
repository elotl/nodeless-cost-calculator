import math
import os
import json
import logging

# load instance data for aws and azure
#

t_unlimited_price = 0.05



class InstanceSelector(object):
    def __init__(self, cloud, region,
                 inst_data_by_region, custom_inst_data_by_region):
        self.cloud = cloud
        self.inst_data = inst_data_by_region[region]
        self.custom_data = custom_inst_data_by_region.get(region, {})

    def price_for_cpu_spec(self, cpu, inst):
        if not inst['burstable']:
            return inst['price'], False
        elif cpu <= inst['baseline']:
            return inst['price'], False
        elif self.cloud == 'aws':
            cpu_needed = cpu - inst['baseline']
            extra_cpu_cost = cpu_needed * t_unlimited_price
            cost = inst['price'] + extra_cpu_cost
            return cost, True
        return -1, False

    def find_cheapest_instance(self, insts):
        lowest_price = 100000000.0
        cheapest_instance = ""
        for inst in insts:
            if inst['price'] > 0 and inst['price'] < lowest_price:
                lowest_price = inst['price']
                cheapest_instance = inst['instanceType']
        return cheapest_instance, lowest_price

    def cheapest_custom_instance(self, cid, cpu_request, memory_request):
        custom_price = 100000000.0
        custom_cpus = 10000000000
        custom_memory = 10000000000
        mem_ceiling = math.ceil(float(memory_request) / cid['baseMemoryUnit'])
        base_mem_size = cid['baseMemoryUnit'] * mem_ceiling
        for cpu in cid['possibleNumberOfCPUs']:
            if (cpu_request < cpu < custom_cpus and
                    base_mem_size <= cid['maximumMemoryPerCPU'] * cpu):
                memory = base_mem_size
                if memory < cid['minimumMemoryPerCPU'] * cpu:
                    memory = cid['minimumMemoryPerCPU'] * cpu
                price = (memory * cid['pricePerGBOfMemory'] +
                         cpu * cid['pricePerCPU'])
                if price < custom_price:
                    custom_price = price
                    custom_cpus = cpu
                    custom_memory = memory
        return custom_cpus, custom_memory, custom_price

    def get_custom_instances(self, cpu_request, memory_request, gpu_spec):
        inst_data = []
        for cid in self.custom_data:
            if (cid['baseMemoryUnit'] == 0.0 or
                    len(cid['possibleNumberOfCPUs']) < 1):
                continue
            custom_cpus, custom_memory, price = self.cheapest_custom_instance(
                cid, cpu_request, memory_request)
            if not custom_cpus or not custom_memory:
                continue
            max_gpus = 0
            for _, gpu in cid.get('supportedGPUTypes', {}).items():
                if gpu > max_gpus:
                    max_gpus = gpu
            instance_type = '{}-custom-{}-{}'.format(
                cid['instanceFamily'], custom_cpus, custom_memory)
            inst_data.append({
                'instanceType':      instance_type,
                'price':             price,
                'gpu':               max_gpus,
                'supportedGPUTypes': cid['supportedGPUTypes'],
                'memory':            custom_memory,
                'cpu':               custom_cpus,
                'burstable':         False,
                'baseline':          custom_cpus,
            })
        return inst_data

    def parse_gpu_spec(self, gpu_spec):
        gpu_count = 0
        gpu_type = ''
        if gpu_spec:
            try:
                parts = gpu_spec.split(' ')
                gpu_count = int(parts[0])
                gpu_type = ' '.join(parts[1:])
            except Exception as e:
                logging.error('invalid GPU spec: %s: %s', gpu_spec, str(e))
        return gpu_count, gpu_type

    def gpu_matches(self, gpu_count, gpu_type, inst):
        if gpu_type == '':
            return inst['gpu'] >= gpu_count
        supported_gpus = inst.get('supportedGPUTypes', {}).get(gpu_type, 0)
        return supported_gpus >= gpu_count

    def get_cheapest_instance(self, cpu_request, memory_request, gpu_spec):
        gpu_count, gpu_type = self.parse_gpu_spec(gpu_spec)
        matches = self.inst_data
        matches += self.get_custom_instances(
            cpu_request, memory_request, gpu_spec)
        matches = [inst for inst in matches
                   if (memory_request == 0.0 or
                       inst['memory'] >= memory_request)]
        matches = [inst for inst in matches
                   if (cpu_request == 0.0 or
                       inst['cpu'] >= cpu_request)]
        matches = [inst for inst in matches
                   if self.gpu_matches(gpu_count, gpu_type, inst)]
        cheapest_instance = ""
        lowest_price = 100000000.0
        for inst in matches:
            price, is_t_unlimited = self.price_for_cpu_spec(cpu_request, inst)
            if price > 0.0 and price < lowest_price:
                lowest_price = price
                cheapest_instance = inst['instanceType']
                if is_t_unlimited:
                    cheapest_instance += ' (unlimited)'
        return cheapest_instance, lowest_price


def make_instance_selector(datadir, cloud, region):
    filename = '{}_instance_data.json'.format(cloud)
    jsonstr = open(os.path.join(datadir, filename)).read()
    inst_data_by_region = json.loads(jsonstr)
    filename = '{}_custom_instance_data.json'.format(cloud)
    custom_inst_data_by_region = {}
    if os.path.exists(filename):
        jsonstr = open(os.path.join(datadir, filename)).read()
        custom_inst_data_by_region = json.loads(jsonstr)
    return InstanceSelector(cloud, region,
                            inst_data_by_region, custom_inst_data_by_region)


def tests(datadir):
    tests = [
        ('aws', 'us-east-1'),
        ('azure', 'East US 2'),
        ('gce', 'us-west1-a'),
    ]
    for cloud, region in tests:
        instance_selector = make_instance_selector(datadir, cloud, region)
        print(instance_selector.get_cheapest_instance(1, 1, ''))
        print(instance_selector.get_cheapest_instance(1, 8, ''))
        print(instance_selector.get_cheapest_instance(.2, 1, ''))
        print(instance_selector.get_cheapest_instance(.8, 8, ''))
        print(instance_selector.get_cheapest_instance(.9, 8, ''))
        print(instance_selector.get_cheapest_instance(2, 8, ''))
        print(instance_selector.get_cheapest_instance(0, 0, ''))


def main():
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    datadir = os.path.join(scriptdir, 'instance-data')
    tests(datadir)


if __name__ == '__main__':
    main()
