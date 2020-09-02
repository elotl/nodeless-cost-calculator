#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
download_dir=$SCRIPT_DIR/cost_calculator/instance-data
mkdir $download_dir

declare -a instance_data_files=("aws_instance_data.json" "azure_instance_data.json" "gce_instance_data.json" "gce_custom_instance_data.json")
for filename in "${instance_data_files[@]}"; do
    echo $filename
    curl https://elotl-cloud-data.s3.amazonaws.com/$filename > $download_dir/$filename
done
