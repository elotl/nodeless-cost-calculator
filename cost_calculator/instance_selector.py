import ast
import math
import os
import json
import logging

# load instance data for aws and azure
#
import redis

t_unlimited_price = 0.05

def cheapest_custom_instance(cid, cpu_request, memory_request):
    max_price = 100000000.0
    custom_price = max_price
    custom_cpus = 10000000000
    custom_memory = 10000000000
    mem_ceiling = math.ceil(float(memory_request) / cid['baseMemoryUnit'])
    base_mem_size = cid['baseMemoryUnit'] * mem_ceiling
    for cpu in cid['possibleNumberOfCPUs']:
        if (cpu_request <= cpu < custom_cpus and
                base_mem_size <= cid['maximumMemoryPerCPU'] * cpu):
            memory = base_mem_size
            if memory < cid['minimumMemoryPerCPU'] * cpu:
                memory = cid['minimumMemoryPerCPU'] * cpu
            ceil = math.ceil(memory / cid['baseMemoryUnit'])
            memory = ceil * cid['baseMemoryUnit']
            price = (memory * cid['pricePerGBOfMemory'] +
                     cpu * cid['pricePerCPU'])
            if price < custom_price:
                custom_price = price
                custom_cpus = cpu
                custom_memory = memory
    if custom_price == max_price:
        return None, None, max_price
    return custom_cpus, custom_memory, custom_price


def parse_gce_custom_machine(inst_type):
    try:
        parts = inst_type.split('-')
        # gce will label an n1-custom node without the family
        # part of the name. e.g. custom-2-3840
        if inst_type.startswith('custom'):
            family = 'n1'
            cpu_str = parts[1]
            memory_str = parts[2]
        else:
            family = parts[0]
            cpu_str = parts[2]
            memory_str = parts[3]
        cpu = int(cpu_str)
        gb_memory = int(memory_str) / 1024.0
        return family, cpu, gb_memory
    except Exception:
        return '', 0, 0.0


class InstanceSelector(object):
    def __init__(
            self,
            cloud,
            region,
            inst_data_by_region,
            custom_inst_data_by_region,
            price_getter=None,
            redis_client=None
    ):
        self.cloud = cloud
        self.inst_data = inst_data_by_region[region]
        self.custom_data = custom_inst_data_by_region.get(region, {})
        self.redis = redis_client
        self.price_getter = price_getter
        self.region = region

    def spec_for_inst_type(self, inst_type):
        if 'custom' in inst_type:
            family, cpu, gb_memory = parse_gce_custom_machine(inst_type)
            if cpu == 0 or gb_memory == 0:
                return None
            price = self.price_for_gce_custom_instance(family, cpu, gb_memory)
            if price is None:
                return None
            return {
                'instanceType':      inst_type,
                'price':             price,
                'gpu':               0,
                'supportedGPUTypes': [],
                'memory':            gb_memory,
                'cpu':               cpu,
                'burstable':         False,
                'baseline':          cpu,
            }
        else:
            for inst in self.inst_data:
                if inst_type == inst["instanceType"]:
                    return inst

    def price_for_gce_custom_instance(self, family, cpu, gb_memory):
        for data in self.custom_data:
            if family != data['instanceFamily']:
                continue
            return (cpu * data['pricePerCPU'] +
                    gb_memory * data['pricePerGBOfMemory'])
        return None

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

    def get_custom_instances(self, cpu_request, memory_request, gpu_spec):
        inst_data = []
        for cid in self.custom_data:
            if (cid['baseMemoryUnit'] == 0.0 or
                    len(cid['possibleNumberOfCPUs']) < 1):
                continue
            custom_cpus, custom_memory, price = cheapest_custom_instance(
                cid, cpu_request, memory_request)
            if not custom_cpus or not custom_memory:
                continue
            max_gpus = 0
            for _, gpu in cid.get('supportedGPUTypes', {}).items():
                if gpu > max_gpus:
                    max_gpus = gpu
            instance_type = '{}-custom-{}-{}'.format(
                cid['instanceFamily'], custom_cpus, int(custom_memory*1024))
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

    def get_spot_price(self, instance_type):
        spot_price = 10000000.0
        if self.price_getter:
            spot_price = self.price_getter.get_spot_price(instance_type, self.region)
        return spot_price

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
            if 0.0 < price < lowest_price:
                lowest_price = price
                cheapest_instance = inst['instanceType']
                if is_t_unlimited:
                    cheapest_instance += ' (unlimited)'
        lowest_spot_price = lowest_price
        lowest_spot_price = min(lowest_spot_price, self.get_spot_price(cheapest_instance))
        return cheapest_instance, lowest_price, lowest_spot_price


class PriceGetter:
    provider_keys_map = {
        "azure": "azure",
        "aws": "amazon",
        "gce": "google"
    }

    def __init__(self, provider, redis_client):
        self.provider = provider
        self.redis_client = redis_client
        self.key_pattern = "/banzaicloud.com/cloudinfo/providers/{provider}/regions/{region}/prices/{instance_type}"

    def _get_azure_region_key(self, region):
        return region.replace(" ", "").lower()

    def _get_key(self, instance_type, region):
        provider = self.provider_keys_map[self.provider]
        if provider == "azure":
            region = self._get_azure_region_key(region)
        return self.key_pattern.format(provider=provider, region=region, instance_type=instance_type)

    def _convert_entry_to_dict(self, data):
        prices_str = data.decode('utf-8')
        if "null" in prices_str:
            prices_str = prices_str.replace("null", "{}")
        print(f"got raw data: {prices_str}")
        try:
            prices = ast.literal_eval(prices_str)
        except ValueError:
            raise ValueError(f"cannot convert {prices_str} to dict")
        return prices

    def _get_lowest_spot_price(self, prices):
        spot_prices = prices.get("spotPrice")
        if spot_prices is None or len(spot_prices.values()) == 0:
            # no spotPrices found, get on-demand price
            return prices['onDemandPrice']
        return min(spot_prices.values())

    def _get_data_for_instance(self, instance_type, region):
        key = self._get_key(region=region, instance_type=instance_type)
        data = self.redis_client.get(key)
        prices = self._convert_entry_to_dict(data)
        return prices

    def get_spot_price(self, instance_type, region):
        prices = self._get_data_for_instance(instance_type, region)
        spot_price = self._get_lowest_spot_price(prices)
        return spot_price
    #
    # def get_ondemand_price(self, instance_type, region):
    #     prices = self._get_data_for_instance(instance_type, region)
    #     return prices['onDemandPrice']


def make_instance_selector(datadir, cloud_provider, region):
    filename = '{}_instance_data.json'.format(cloud_provider)
    filepath = os.path.join(datadir, filename)
    with open(filepath) as fp:
        jsonstr = fp.read()
    inst_data_by_region = json.loads(jsonstr)
    filename = '{}_custom_instance_data.json'.format(cloud_provider)
    filepath = os.path.join(datadir, filename)
    custom_inst_data_by_region = {}
    if os.path.exists(filepath):
        with open(filepath) as fp:
            jsonstr = fp.read()
            custom_inst_data_by_region = json.loads(jsonstr)
    redis_client = redis.Redis("localhost", 6379)
    price_getter = PriceGetter(
        provider=cloud_provider,
        redis_client=redis_client
    )
    return InstanceSelector(
        cloud_provider,
        region,
        inst_data_by_region,
        custom_inst_data_by_region,
        price_getter=price_getter,
    )
