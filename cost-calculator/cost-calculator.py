from pprint import pprint
from collections import defaultdict

from flask import Flask
from flask_apscheduler import APScheduler


class PodSpecs:
    def __init__(self, namespace, name, cpu, memory, gpu, instance_type, cost):
        self.namespace = namespace
        self.name = name
        self.cpu = cpu
        self.memory = memory
        self.gpu = gpu
        self.instance_type = instance_type
        self.cost = cost

    def __str__(self):
        return f'<{self.namespace}:{self.name}, {self.instance_type}, {self.cost}>'

    def __repr__(self):
        return str(self)


class CostCalculator:
    def __init__(self):
        self.cost_summary = self.calculate_cost()

    def calculate_cost(self):
        summary = defaultdict(dict)
        summary['default']['foo'] = PodSpecs('default', 'foo', 0, 1024, 0, 'c5.large', 0.32),
        cost_summary = summary
        pprint(cost_summary)


# def calculate_cost():
#     global cost_summary
#     summary = defaultdict(dict)
#     summary['default']['foo'] = PodSpecs('default', 'foo', 0, 1024, 0, 'c5.large', 0.32),
#     cost_summary = summary
#     pprint(cost_summary)


class Config:
    pass


if __name__ == '__main__':
    cost_calculator = CostCalculator()
    config = Config()
    config.JOBS = [
        {
            'id': 'job1',
            'func': cost_calculator.calculate_cost,
            # 'args': (),
            'trigger': 'interval',
            'seconds': 1,
        }
    ]

    app = Flask(__name__)
    app.config.from_object(config)

    scheduler = APScheduler()
    # it is also possible to enable the API directly
    # scheduler.api_enabled = True
    scheduler.init_app(app)
    scheduler.start()

    app.run()
