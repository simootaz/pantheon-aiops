{{/*
Shared helpers.

Phase: 6 - Go Port & Platform Binaries
*/}}
{{- define "pantheon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pantheon.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "pantheon.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "pantheon.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "pantheon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "pantheon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pantheon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "pantheon.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "pantheon.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "pantheon.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s/%s:%s" .Values.image.registry .Values.image.repository $tag -}}
{{- end -}}

{{/*
S3 endpoint: the bundled MinIO when enabled, otherwise the external provider.
Application code never learns which - it only ever reads S3_ENDPOINT_URL.
*/}}
{{- define "pantheon.s3Endpoint" -}}
{{- if .Values.minio.enabled -}}
{{- printf "http://%s-minio:9000" (include "pantheon.fullname" .) -}}
{{- else -}}
{{- required "minio.external.endpoint is required when minio.enabled is false" .Values.minio.external.endpoint -}}
{{- end -}}
{{- end -}}

{{- define "pantheon.s3Region" -}}
{{- if .Values.minio.enabled -}}us-east-1{{- else -}}{{ .Values.minio.external.region }}{{- end -}}
{{- end -}}

{{/*
Name of the secret holding the MinIO credential. Either the operator's
existingSecret, or one this chart generates for evaluation.
*/}}
{{- define "pantheon.minioSecretName" -}}
{{- if .Values.minio.existingSecret -}}
{{- .Values.minio.existingSecret -}}
{{- else -}}
{{- printf "%s-minio" (include "pantheon.fullname" .) -}}
{{- end -}}
{{- end -}}
