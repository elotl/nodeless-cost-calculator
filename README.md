# Nodeless Cost Calculator

The Nodeless Cost Calculator is a dashboard that shows the current cost of your Kubernetes cluster and the projected cost of running an equivalent cluster on Nodeless Kubernetes. The projected cost is calculated by chosing an instance type for each pod based on the resource requests and limits specified in the pod spec.

## Installation

Follow these instructions to install the Nodeless Cost Calculator from the command line.

### Prerequisites

- A Kubernetes cluster
- [Kustomize](https://kustomize.io)

### Install from the command line

You need to set cloud credentials in `kustomize/overlays/<your-provider>/config.toml` and then apply those with `kubectl -k .`
Cloud credentials are used to fetch on-demand and spot prices.

#### AWS
In AWS [config.toml](kustomize/overlays/aws/config.toml)
```toml
region = "us-east-1"

# Static credentials
accessKey = ""
secretKey = ""
```
and then run
`kustomize build kustomize/overlays/azure | kubectl apply -f -`

#### GCE
In GCE [config.toml](kustomize/overlays/gce/config.toml):
```toml
# base64 encoded credentials in json format (base64 encoded content of the credential file)
credentials = ""

# credentialsFile = ""

# project = ""
```
and then run
`kustomize build kustomize/overlays/gce | kubectl apply -f -`

#### Azure
In Azure [config.toml](kustomize/overlays/azure/config.toml): 
```toml
subscriptionId = ""

# Client credentials
clientId = ""
clientSecret = ""
tenantId = ""
```
and then run
`kustomize build kustomize/overlays/azure | kubectl apply -f -`

Scraping spot prices usually takes up to 5-7 minutes. Once it's done you should see that all containers are ready:
`nodeless-cost-calculator-5567f8585-b9d5z   3/3     Running   0          5m8s`

Once the nodeless-cost-calculator deployment is running, the easiest way to connect to the pod is to use `kubectl port-forward`

    kubectl -n$NAMESPACE port-forward $(kubectl -n$NAMESPACE get pod -l app.kubernetes.io/name=nodeless-cost-calculator -o custom-columns=:metadata.name --no-headers) 5000

## Uninstall

    kubectl -n$NAMESPACE delete Deployment,ServiceAccount,ClusterRole,ClusterRoleBinding -l app.kubernetes.io/name=nodeless-cost-calculator

## Running with static data input
Once you have data about nodes and pods in json, you can run cost calculator in your local cluster and still get calculated results.
To do this, you need to overwrite [input_example.json](kustomize/overlays/file-input).

1. Get nodes data:
`kubectl get nodes -o json | jq -r '.items[] | {name: .metadata.name, labels: .metadata.labels}' > nodes.json`
2. Get workloads data: 
`kubectl get pods --all-namespaces -o json | jq -r '.items[] | { name: .metadata.name, namespace: .metadata.namespace, containers: .spec.containers[].resources, initContainers: .spec.initContainers }' > pods.json`
3. Place files in `scripts` and run `python data_sanitizer.py` from there. This will create input file from your data for cost-calculator. 
4. Copy this file to `kustomize/overlays/file-input/input_example.json`.
Now you're ready to deploy cost-calculator to your cluster using
`kustomize build kustomize/overlays/file-input | kubectl apply -f -`


## Unsupported features

* Reserved instance pricing
* Custom cloud pricing
* Storage costs
* Network costs
* Cost of nodes with GPU instances
