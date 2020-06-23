# Nodeless Cost Calculator

_A work in progress_

## Suggested Architecture

1. A flask app that users connect to that displays the calculated cost. This might include a graph of the cost over time
2. A background task that runs periodically. That lists pods and sums their cost
3. Need a python instanceSelector
4. Need files with cloud pricing data

## Arguments

    --cloud-provider
    --region
    --namespace
    --default-instance-type
    --interval (default to every minute)

## RBAC Credentials
