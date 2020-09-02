FROM python:3.8.3-buster

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

ENV CLOUD_PROVIDER=aws
ENV REGION=us-east-1

ENTRYPOINT ["/usr/local/bin/gunicorn", "-k", "gevent", "-w", "4", "-b", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "cost_calculator:app"]
