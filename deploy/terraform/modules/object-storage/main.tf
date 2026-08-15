# Object storage - provider-shaped, not vendor-shaped.
#
# Phase: 7 - Production Hardening
# Renamed from modules/s3 per docs/adr/0001-object-storage-minio.md.
# Takes an S3-compatible endpoint rather than assuming one cloud, so the same
# module serves MinIO, Ceph RADOS Gateway, AWS S3, Wasabi, B2 and R2.

# Bucket resources land at Phase 7 behind a provider the operator selects.
# The module stays provider-shaped: application code only ever reads
# S3_ENDPOINT_URL, so swapping the backend is a variable change.
#
# TODO: Phase 7 - create buckets, lifecycle rules and access policies
