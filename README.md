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


## Unsupported features

* Reserved instance pricing
* Custom cloud pricing
* Storage costs
* Network costs
* Cost of nodes with GPU instances
