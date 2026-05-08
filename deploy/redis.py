"""Redis for the Triple-DB stack via **Kubernetes** or **AWS ElastiCache**.

``maxmemory-policy`` is always set to **allkeys-lru** so volatile keys (e.g. rate-limit / signature
caches) can evict under memory pressure without blocking writes on an out-of-memory condition.

- ``triple-db:redisBackend`` = ``kubernetes`` (default) or ``aws``.
"""

from __future__ import annotations

import pulumi
import pulumi_aws as aws
from pulumi_kubernetes.apps.v1 import Deployment, DeploymentSpecArgs
from pulumi_kubernetes.core.v1 import (
    ConfigMap,
    ConfigMapVolumeSourceArgs,
    ContainerArgs,
    ContainerPortArgs,
    PodSpecArgs,
    PodTemplateSpecArgs,
    Service,
    ServicePortArgs,
    ServiceSpecArgs,
    VolumeArgs,
    VolumeMountArgs,
)
from pulumi_kubernetes.meta.v1 import LabelSelectorArgs, ObjectMetaArgs

_APP_LABEL = "tarka-redis"
_MANAGED_BY = "pulumi-triple-db"


def _redis_conf(maxmemory: str) -> str:
    return (
        "# Managed by deploy/redis.py (Triple-DB Pulumi)\n"
        f"maxmemory {maxmemory}\n"
        "maxmemory-policy allkeys-lru\n"
    )


def _provision_kubernetes(*, cfg: pulumi.Config) -> None:
    ns = cfg.get("redisNamespace") or "tarka"
    maxmem = cfg.get("redisMaxmemory") or "256mb"
    image = cfg.get("redisImage") or "redis:7-alpine"
    replicas = int(cfg.get("redisReplicas") or "1")

    labels = {"app": _APP_LABEL, "managed-by": _MANAGED_BY}
    cfgmap_name = "tarka-redis-config"

    cm = ConfigMap(
        "triple-db-redis-config",
        metadata=ObjectMetaArgs(
            name=cfgmap_name,
            namespace=ns,
            labels=labels,
        ),
        data={"redis.conf": _redis_conf(maxmem)},
    )

    deploy = Deployment(
        "triple-db-redis-deployment",
        metadata=ObjectMetaArgs(
            name="tarka-redis",
            namespace=ns,
            labels=labels,
        ),
        spec=DeploymentSpecArgs(
            replicas=replicas,
            selector=LabelSelectorArgs(match_labels={"app": _APP_LABEL}),
            template=PodTemplateSpecArgs(
                metadata=ObjectMetaArgs(labels={"app": _APP_LABEL}),
                spec=PodSpecArgs(
                    containers=[
                        ContainerArgs(
                            name="redis",
                            image=image,
                            image_pull_policy="IfNotPresent",
                            ports=[ContainerPortArgs(name="redis", container_port=6379)],
                            command=["redis-server", "/etc/redis/redis.conf"],
                            volume_mounts=[
                                VolumeMountArgs(
                                    name="redis-config",
                                    mount_path="/etc/redis",
                                    read_only=True,
                                )
                            ],
                            readiness_probe={
                                "tcp_socket": {"port": 6379},
                                "initial_delay_seconds": 5,
                                "period_seconds": 5,
                            },
                            liveness_probe={
                                "tcp_socket": {"port": 6379},
                                "initial_delay_seconds": 15,
                                "period_seconds": 10,
                            },
                        )
                    ],
                    volumes=[
                        VolumeArgs(
                            name="redis-config",
                            config_map=ConfigMapVolumeSourceArgs(
                                name=cfgmap_name,
                            ),
                        )
                    ],
                ),
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=[cm]),
    )

    Service(
        "triple-db-redis-service",
        metadata=ObjectMetaArgs(
            name="tarka-redis",
            namespace=ns,
            labels=labels,
        ),
        spec=ServiceSpecArgs(
            type="ClusterIP",
            selector={"app": _APP_LABEL},
            ports=[
                ServicePortArgs(name="redis", port=6379, target_port=6379, protocol="TCP"),
            ],
        ),
        opts=pulumi.ResourceOptions(depends_on=[deploy]),
    )

    pulumi.export(
        "redisKubernetesFqdn",
        pulumi.Output.from_input(f"tarka-redis.{ns}.svc.cluster.local:6379"),
    )


def _provision_aws_elasticache(*, cfg: pulumi.Config) -> None:
    vpc_id = cfg.require("redisVpcId")
    subnet_csv = cfg.require("redisElasticacheSubnetIds")
    subnet_ids = [s.strip() for s in subnet_csv.split(",") if s.strip()]
    if not subnet_ids:
        raise ValueError("redisElasticacheSubnetIds must list at least one subnet id")

    rep_id = cfg.require("redisReplicationGroupId")
    node_type = cfg.get("redisNodeType") or "cache.t4g.micro"
    engine_version = cfg.get("redisEngineVersion") or "7.1"

    cidr_csv = cfg.require("redisAllowedCidrBlocks")
    cidrs = [c.strip() for c in cidr_csv.split(",") if c.strip()]
    if not cidrs:
        raise ValueError("redisAllowedCidrBlocks must list at least one CIDR")

    param_group = aws.elasticache.ParameterGroup(
        "triple-db-redis-params",
        family="redis7",
        description="Tarka Triple-DB Redis (maxmemory-policy=allkeys-lru)",
        parameters=[
            aws.elasticache.ParameterGroupParameterArgs(
                name="maxmemory-policy",
                value="allkeys-lru",
            ),
        ],
    )

    subnet_group = aws.elasticache.SubnetGroup(
        "triple-db-redis-subnets",
        name=f"{rep_id}-subnets",
        subnet_ids=subnet_ids,
    )

    sg = aws.ec2.SecurityGroup(
        "triple-db-redis-sg",
        name=f"{rep_id}-sg",
        description="Redis ElastiCache access for Tarka Triple-DB",
        vpc_id=vpc_id,
        ingress=[
            aws.ec2.SecurityGroupIngressArgs(
                description="Redis from allowed CIDRs",
                protocol="tcp",
                from_port=6379,
                to_port=6379,
                cidr_blocks=cidrs,
            )
        ],
        egress=[
            aws.ec2.SecurityGroupEgressArgs(
                protocol="-1",
                from_port=0,
                to_port=0,
                cidr_blocks=["0.0.0.0/0"],
                description="Allow all outbound (AWS default pattern)",
            )
        ],
    )

    rg = aws.elasticache.ReplicationGroup(
        "triple-db-redis-elasticache",
        replication_group_id=rep_id,
        description="Tarka Triple-DB Redis (ElastiCache)",
        engine="redis",
        engine_version=engine_version,
        node_type=node_type,
        port=6379,
        parameter_group_name=param_group.name,
        subnet_group_name=subnet_group.name,
        security_group_ids=[sg.id],
        automatic_failover_enabled=False,
        multi_az_enabled=False,
        num_cache_clusters=1,
        at_rest_encryption_enabled=True,
        transit_encryption_enabled=False,
        apply_immediately=True,
        opts=pulumi.ResourceOptions(depends_on=[param_group, subnet_group, sg]),
    )

    pulumi.export(
        "redisElasticachePrimaryAddress",
        rg.primary_endpoint_address,
    )
    pulumi.export("redisElasticacheReaderAddress", rg.reader_endpoint_address)


def provision(*, cfg: pulumi.Config | None = None) -> None:
    """Provision Redis on Kubernetes or AWS per ``triple-db:redisBackend``."""
    cfg = cfg or pulumi.Config()
    backend = (cfg.get("redisBackend") or "kubernetes").lower()
    if backend == "kubernetes":
        _provision_kubernetes(cfg=cfg)
    elif backend == "aws":
        _provision_aws_elasticache(cfg=cfg)
    else:
        raise ValueError(
            f"Unsupported triple-db:redisBackend={backend!r}; use 'kubernetes' or 'aws'."
        )
