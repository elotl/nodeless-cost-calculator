# Nodeless Cost Calculator

The Nodeless Cost Calculator is a dashboard that shows the current cost of your Kubernetes cluster and the projected cost of running an equivalent cluster on Nodeless Kubernetes. The projected cost is calculated by chosing an instance type for each pod based on the resource requests and limits specified in the pod spec.

## Installation

Follow these instructions to install the Nodeless Cost Calculator from the command line.

### Prerequisites

- A Kubernetes cluster
- [envsubst](https://www.gnu.org/software/gettext/manual/html_node/envsubst-Invocation.html)

### Install from the command line

Set environment variables (modify if necessary) and apply the manifests:

**AWS**

    export NAMESPACE=default
    export CLOUD_PROVIDER=aws
    export REGION=us-east-1

**GCE**

    export NAMESPACE=default
    export CLOUD_PROVIDER=gce
    export REGION=us-east1

**Azure**

    export NAMESPACE=default
    export CLOUD_PROVIDER=azure
    export REGION="East US"

    envsubst < manifests.yaml | kubectl apply -f -

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
