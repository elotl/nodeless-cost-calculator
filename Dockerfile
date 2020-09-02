FROM python:3.8.3-buster

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

WORKDIR /app/cost_calculator

# CMD ["flask", "run", "--host", "0.0.0.0"]

ENTRYPOINT ["/usr/local/bin/gunicorn", "-k", "gevent", "-w", "4", "-b", ":5000", "--access-logfile", "-", "--error-logfile", "-", "cost_calculator:app"]
