"""Automation Lambda responds to Splunk alerts and takes actions"""

import json
import boto3
import jira
import settings

def lambda_handler(event, context):
    """Handle alerts from Splunk and automate all the things"""
    message = json.loads(event["Records"][0]["Sns"]["Message"])
    action = message["message"]
    alert_data = json.loads(message["event"])
    search_name = message["search_name"]
    print(event)
    if action == "create_ticket":
        summary = f"Splunk Alert: {search_name}"
        print(f"Creating ticket for {summary}")
        create_ticket(summary, json.dumps(alert_data))
    elif action == "remediate_security_groups":
        remediate_open_security_groups()


def create_ticket(summary, description):
    j = jira.JIRA(
        settings.jira_url,
        basic_auth=(settings.jira_username, settings.jira_password),
    )

    issue = j.create_issue(
        project=settings.jira_project,
        summary=summary,
        description=description,
        issuetype="Task",
    )
    return issue


def open_security_groups():
    """Return all security groups that are allow inbound connections from the """
    ec2_client = boto3.client("ec2")
    security_groups = ec2_client.describe_security_groups(
        Filters=[
            {"Name": "ip-permission.cidr", "Values": ["0.0.0.0/0"]},
        ]
    )
    groups_whitelist = ["sg-085e22931921563de"]
    ports_whitelist = [22, 80, 443, 8080]
    open_groups = []
    for sg in security_groups["SecurityGroups"]:
        for permission in sg["IpPermissions"]:
            if sg["GroupId"] not in groups_whitelist and permission["ToPort"] not in ports_whitelist:
                open_groups.append(sg["GroupId"])
    return list(set(open_groups))


def instance_security_groups():
    """Return a summary of all the security group IDs assocated with running instances.

    This format will look like:
        {'i-096e3b9655241f365': ['sg-05777ecea90c47aae'], ...}
    """
    ec2_client = boto3.client("ec2")
    running_instances = ec2_client.describe_instances(
        Filters=[
            {"Name": "instance-state-name", "Values": ["running", "stopped"]},
        ]
    )
    instances = {}
    for reservation in running_instances["Reservations"]:
        for instance in reservation["Instances"]:
            instance_id = instance["InstanceId"]
            for iface in instance["NetworkInterfaces"]:
                instances[instance_id] = []
                for group in iface["Groups"]:
                    instances[instance_id].append(group["GroupId"])
    return instances


def remove_security_group(instance_id, sg_id):
    ec2 = boto3.client('ec2')
    group_name = 'default'
    response = ec2.describe_security_groups(
        Filters=[
            dict(Name='group-name', Values=[group_name])
        ]
    )
    default_group_id = response['SecurityGroups'][0]['GroupId']
    ec2_resource = boto3.resource("ec2")
    instance = ec2_resource.Instance(instance_id)
    new_groups = [g["GroupId"] for g in instance.security_groups if g["GroupId"] != sg_id]
    # Security groups can't be empty, so if this list is empty use the default security group
    if not new_groups:
        new_groups = [default_group_id]
    instance.modify_attribute(Groups=new_groups)


def remediate_open_security_groups():
    open_groups = open_security_groups()
    instance_groups = instance_security_groups()
    ticket_description = ""
    for instance, groups in instance_groups.items():
        instance_open_groups = list(set(groups).intersection(open_groups))
        for group in instance_open_groups:
            ticket_description += f"Removing {group} from {instance}\n"
            remove_security_group(instance, group)
    if not ticket_description:
        print("No open security groups - No action taken")
    issue = create_ticket("Remediated security groups", ticket_description)
    print(f"Created {issue.key}: {ticket_description}")
