# Nodeless Cost Calculator

The Nodeless Cost Calculator is a dashboard that shows you the current cost of your Kubernetes cluster and the projected cost of running an equivalent cluster on Nodeless Kubernetes. The projected cost is calculated by chosing an instance type for each pod based on the resource requests and limits specified in the pod spec.

Unsupported features:

* Reserved instance pricing
* Custom cloud pricing
* Storage costs
* Network costs

## Installation

Follow these instructions to install the Nodeless Cost Calculator from the command line.

### Prerequisites

- A Kubernetes cluster
- [envsubst](https://www.gnu.org/software/gettext/manual/html_node/envsubst-Invocation.html)

### Install from the command line

Set environment variables (modify if necessary) and apply the manifests:

    export NAMESPACE=default
    export CLOUD_PROVIDER=aws  # must be one of 'aws' or 'gce'
    export REGION=us-east-1

    envsubst < manifests.yaml | kubectl apply -f -

## Uninstall

    kubectl -n$NAMESPACE delete Deployment,ServiceAccount,ClusterRole,ClusterRoleBinding -l app.kubernetes.io/name=nodeless-cost-calculator