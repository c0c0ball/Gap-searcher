"""암호화 관측: EBS·S3·KMS·로드밸런서 리스너 스냅샷을 Observation으로 바꾼다 (2.7 암호화).

스냅샷 파일 (계정 폴더마다)
  ec2_volumes.json          DescribeVolumes 응답의 Volumes 목록
  s3_buckets.json           [{Name, Region, Encryption: GetBucketEncryption 규칙 목록 | Error}]
  kms_keys.json             [{KeyId, Arn, KeyManager, KeyState, Aliases, KeyRotationEnabled}]
                            (ListKeys → DescribeKey, ListAliases, GetKeyRotationStatus 를 합친 것)
  elbv2_listeners.json      [{LoadBalancerName, LoadBalancerArn, Scheme, Listeners: [DescribeListeners …]}]
  elbv2_ssl_policies.json   DescribeSSLPolicies 응답의 SslPolicies 목록 (리스너가 쓰는 정책만)

RDS 저장 암호화는 rds_db_instances.json 을 network.py 와 함께 쓴다 (aws_db 관측에 필드 추가).

관측 kind
  aws_volume    EBS 볼륨 (암호화 여부, 키)
  aws_bucket    S3 버킷 (기본 암호화 방식, 키)
  aws_kms_key   KMS 키 (관리 주체, 자동 교체)
  aws_listener  로드밸런서 리스너 (프로토콜, HTTPS 전환 여부, 최소 TLS)
  aws_key_use   암호화된 리소스 1개가 쓰는 키 (키가 있는 계정)
"""
from __future__ import annotations

import json
from typing import Any

from ..model import Observation

FILES = {"volume": "ec2_volumes.json", "bucket": "s3_buckets.json", "kms": "kms_keys.json",
         "listener": "elbv2_listeners.json", "ssl": "elbv2_ssl_policies.json"}
TLS = {"SSLv3": 0.3, "TLSv1": 1.0, "TLSv1.1": 1.1, "TLSv1.2": 1.2, "TLSv1.3": 1.3}


def _load(f: dict[str, bytes], name: str) -> list | None:
    if name not in f:
        return None
    body = json.loads(f[name])
    return None if isinstance(body, dict) and "Error" in body else body


def key_account(key: str | None, own: str) -> str | None:
    """KMS 키 ARN이면 그 계정, 키 ID·별칭이면 리소스와 같은 계정으로 본다."""
    if not key:
        return None
    if key.startswith("arn:aws:kms:"):
        return key.split(":")[4]
    return own


def crypto_observations(aid: str, f: dict[str, bytes], sha: dict[str, str], src: dict) -> list[Observation]:
    vols, buckets, keys, lbs, ssl = (_load(f, FILES[k]) for k in ("volume", "bucket", "kms", "listener", "ssl"))
    obs: list[Observation] = []

    def o(kind: str, oid: str, subject: str, values: dict, files: list[str], api: str) -> Observation:
        return Observation(obs_id=f"aws:{aid}:{oid}", axis="technical", kind=kind, subject=subject,
                           values={"account_id": aid, **values}, extractor=src["source"],
                           source={**src, "sha256": [sha[f"{aid}/{x}"] for x in files if f"{aid}/{x}" in sha],
                                   "api": api})

    def key_use(res_kind: str, res_id: str, name: str, key: str | None, file: str, api: str) -> None:
        if not key:
            return
        ka = key_account(key, aid)
        obs.append(o("aws_key_use", f"keyuse:{res_kind}:{res_id}", f"{aid}/{res_id}", {
            "key": f"{aid}/{res_id}", "resource_kind": res_kind, "resource": name, "kms_key": key,
            "key_account": ka, "cross_account": ka != aid}, [file], api))

    aliases_by_id: dict[str, list[str]] = {}
    for k in keys or []:
        aliases_by_id[k["KeyId"]] = k.get("Aliases", [])
        customer = k.get("KeyManager") == "CUSTOMER"
        alias = ", ".join(k.get("Aliases", [])) or k["KeyId"]
        obs.append(o("aws_kms_key", f"kms:{k['KeyId']}", f"{aid}/{k['KeyId']}", {
            "key": f"{aid}/{k['KeyId']}", "key_id": k["KeyId"], "alias": alias,
            "manager": k.get("KeyManager"), "customer_managed": customer,
            "enabled": k.get("KeyState") == "Enabled", "description": k.get("Description", ""),
            # AWS 관리형 키는 AWS가 매년 자동 교체하므로 고객이 설정할 대상이 아니다
            "rotation_enabled": bool(k.get("KeyRotationEnabled")) if customer else None,
        }, [FILES["kms"]], "kms:ListKeys+kms:DescribeKey+kms:GetKeyRotationStatus"))

    for v in vols or []:
        vid = v["VolumeId"]
        tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
        name = tags.get("Name", vid)
        attached = [a["InstanceId"] for a in v.get("Attachments", [])]
        obs.append(o("aws_volume", f"ebs:{vid}", f"{aid}/{vid}", {
            "key": f"{aid}/{vid}", "volume_id": vid, "name": name, "encrypted": bool(v.get("Encrypted")),
            "kms_key": v.get("KmsKeyId"), "attached_to": attached, "size_gb": v.get("Size"),
        }, [FILES["volume"]], "ec2:DescribeVolumes"))
        if v.get("Encrypted"):
            key_use("ebs", vid, name, v.get("KmsKeyId"), FILES["volume"], "ec2:DescribeVolumes")

    for b in buckets or []:
        name = b["Name"]
        enc = b.get("Encryption")
        algo, kms = None, None
        if isinstance(enc, list) and enc:
            d = enc[0].get("ApplyServerSideEncryptionByDefault", {})
            algo, kms = d.get("SSEAlgorithm"), d.get("KMSMasterKeyID")
        obs.append(o("aws_bucket", f"s3:{name}", f"{aid}/{name}", {
            "key": f"{aid}/{name}", "bucket": name, "sse_algorithm": algo or "없음",
            "kms_encrypted": algo in ("aws:kms", "aws:kms:dsse"), "kms_key": kms,
        }, [FILES["bucket"]], "s3:ListBuckets+s3:GetBucketEncryption"))
        if algo in ("aws:kms", "aws:kms:dsse"):
            key_use("s3", name, name, kms, FILES["bucket"], "s3:GetBucketEncryption")

    rds = _load(f, "rds_db_instances.json")
    for d in rds or []:
        if d.get("StorageEncrypted"):
            key_use("rds", d["DBInstanceIdentifier"], d["DBInstanceIdentifier"], d.get("KmsKeyId"),
                    "rds_db_instances.json", "rds:DescribeDBInstances")

    tls_of = {p["Name"]: min((TLS[x] for x in p.get("SslProtocols", []) if x in TLS), default=None)
              for p in ssl or []}
    for lb in lbs or []:
        lname, scheme = lb["LoadBalancerName"], lb.get("Scheme", "internet-facing")
        for li in lb.get("Listeners", []):
            proto, port = li.get("Protocol"), li.get("Port")
            acts = li.get("DefaultActions", [])
            redirect = any(a.get("Type") == "redirect" and (a.get("RedirectConfig") or {}).get("Protocol") == "HTTPS"
                           for a in acts)
            tls = proto in ("HTTPS", "TLS")
            policy = li.get("SslPolicy")
            obs.append(o("aws_listener", f"lb:{lname}:{port}", f"{aid}/{lname}:{port}", {
                "key": f"{aid}/{lname}:{port}", "load_balancer": lname, "scheme": scheme,
                "internet_facing": scheme == "internet-facing", "protocol": proto, "port": port,
                "tls": tls, "redirect_https": redirect,
                # 평문 리스너라도 HTTPS로 넘기기만 하면 개인정보가 평문으로 오가지 않는다
                "plaintext_service": not tls and not redirect,
                "ssl_policy": policy, "tls_min": tls_of.get(policy) if tls else None,
            }, [FILES["listener"], FILES["ssl"]], "elasticloadbalancing:DescribeListeners+DescribeSSLPolicies"))
    return obs


def db_crypto_fields(d: dict, aid: str) -> dict[str, Any]:
    """network.py 의 aws_db 관측에 붙일 저장 암호화 필드"""
    key = d.get("KmsKeyId")
    return {"storage_encrypted": bool(d.get("StorageEncrypted")), "kms_key": key,
            "key_account": key_account(key, aid) if d.get("StorageEncrypted") else None}
