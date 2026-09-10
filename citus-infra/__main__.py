import pulumi
import pulumi_aws as aws
import os

# Configuration
instance_type = "t2.micro"
ami_id = "ami-01811d4912b4ccb26"
key_name = "citus-key"

# 1. Networking (VPC, Subnet, Internet Gateway, Route Table)
vpc = aws.ec2.Vpc("citus-vpc",
    cidr_block="10.0.0.0/16",
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={"Name": "citus-vpc"}
)

igw = aws.ec2.InternetGateway("citus-igw",
    vpc_id=vpc.id,
    tags={"Name": "citus-igw"}
)

subnet = aws.ec2.Subnet("citus-subnet",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    map_public_ip_on_launch=True,
    tags={"Name": "citus-subnet"}
)

route_table = aws.ec2.RouteTable("citus-rt",
    vpc_id=vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(
        cidr_block="0.0.0.0/0",
        gateway_id=igw.id,
    )],
    tags={"Name": "citus-rt"}
)

route_table_assoc = aws.ec2.RouteTableAssociation("citus-rt-assoc",
    subnet_id=subnet.id,
    route_table_id=route_table.id
)

# 2. Security Group (SSH port 22, Citus PostgreSQL port 5432)
security_group = aws.ec2.SecurityGroup("citus-sg",
    vpc_id=vpc.id,
    description="Security group for Citus cluster",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=22,
            to_port=22,
            cidr_blocks=["0.0.0.0/0"]
        ),
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=5432,
            to_port=5432,
            cidr_blocks=["0.0.0.0/0"]
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"]
        )
    ],
    tags={"Name": "citus-sg"}
)

# 3. User Data Script for Worker Nodes
worker_user_data = """#!/bin/bash
apt-get update -y
apt-get install -y docker.io docker-compose
systemctl start docker
systemctl enable docker
usermod -aG docker ubuntu

cat << 'EOF' > /home/ubuntu/docker-compose.yml
version: '3.8'
services:
  worker:
    image: citusdata/citus:12.1
    container_name: citus_worker
    restart: always
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_PASSWORD=citus_password
      - POSTGRES_USER=citus
      - POSTGRES_DB=citus
    command: >
      -c citus.shard_replication_factor=2
      -c listen_addresses='*'
      -c wal_level=logical
EOF

docker-compose -f /home/ubuntu/docker-compose.yml up -d
"""

# 4. User Data Script for Coordinator Node
coordinator_user_data = """#!/bin/bash
apt-get update -y
apt-get install -y docker.io docker-compose
systemctl start docker
systemctl enable docker
usermod -aG docker ubuntu

cat << 'EOF' > /home/ubuntu/docker-compose.yml
version: '3.8'
services:
  coordinator:
    image: citusdata/citus:12.1
    container_name: citus_coordinator
    restart: always
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_PASSWORD=citus_password
      - POSTGRES_USER=citus
      - POSTGRES_DB=citus
    command: >
      -c citus.shard_replication_factor=2
      -c listen_addresses='*'
      -c wal_level=logical
EOF

docker-compose -f /home/ubuntu/docker-compose.yml up -d

# Wait for worker instances to boot and start Citus containers
sleep 60

# Automatically register worker nodes in the Citus cluster
docker exec -i citus_coordinator psql -U citus -d citus << 'SQL'
SELECT citus_add_node('10.0.1.20', 5432);
SELECT citus_add_node('10.0.1.21', 5432);
SELECT citus_add_node('10.0.1.22', 5432);
SQL
"""

# 5. Launch Coordinator Instance (Private IP: 10.0.1.10)
coordinator = aws.ec2.Instance("citus-coordinator",
    instance_type=instance_type,
    ami=ami_id,
    subnet_id=subnet.id,
    vpc_security_group_ids=[security_group.id],
    key_name=key_name,
    user_data=coordinator_user_data,
    associate_public_ip_address=True,
    private_ip="10.0.1.10",
    tags={"Name": "citus-coordinator"},
    opts=pulumi.ResourceOptions(depends_on=[route_table_assoc, subnet])
)

# 6. Launch 3 Worker Instances (Private IPs: 10.0.1.20, 10.0.1.21, 10.0.1.22)
workers = [
    aws.ec2.Instance(f"citus-worker-{i}",
        instance_type=instance_type,
        ami=ami_id,
        subnet_id=subnet.id,
        vpc_security_group_ids=[security_group.id],
        key_name=key_name,
        user_data=worker_user_data,
        associate_public_ip_address=True,
        private_ip=f"10.0.1.2{i}",
        tags={"Name": f"citus-worker-{i}"},
        opts=pulumi.ResourceOptions(depends_on=[route_table_assoc, subnet])
    )
    for i in range(3)
]

# 7. Outputs & Automatic SSH Config Generation
pulumi.export('coordinator_public_ip', coordinator.public_ip)
pulumi.export('coordinator_private_ip', coordinator.private_ip)
pulumi.export('worker_public_ips', [w.public_ip for w in workers])
pulumi.export('worker_private_ips', [w.private_ip for w in workers])
pulumi.export('vpc_id', vpc.id)
pulumi.export('subnet_id', subnet.id)

def create_config_file(ip_list):
    hostnames = ['controller-0', 'worker-0', 'worker-1', 'worker-2']
    config_content = "".join([
        f"Host {h}\n    HostName {ip}\n    User ubuntu\n    IdentityFile ~/.ssh/{key_name}.pem\n    StrictHostKeyChecking no\n\n"
        for h, ip in zip(hostnames, ip_list)
    ])
    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    with open(os.path.join(ssh_dir, "config"), "w") as f:
        f.write(config_content)
    os.chmod(os.path.join(ssh_dir, "config"), 0o600)

pulumi.Output.all(*([coordinator.public_ip] + [w.public_ip for w in workers])).apply(create_config_file)
