{{/*
Expand the chart name.
*/}}
{{- define "tarka.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified application name.
*/}}
{{- define "tarka.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Component DNS-safe name (Service / Deployment).
*/}}
{{- define "tarka.component" -}}
{{- printf "%s-%s" (include "tarka.fullname" .) .component | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "tarka.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tarka.name" $ }}
app.kubernetes.io/instance: {{ $.Release.Name }}
{{- end }}

{{/*
Standard labels
*/}}
{{- define "tarka.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "tarka.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "tarka.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "tarka.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "tarka.platformConfigMap" -}}
{{ include "tarka.fullname" . }}-platform-config
{{- end }}

{{- define "tarka.credentialsSecret" -}}
{{- if .Values.credentials.existingSecretName }}
{{- .Values.credentials.existingSecretName }}
{{- else }}
{{- printf "%s-credentials" (include "tarka.fullname" .) }}
{{- end }}
{{- end }}

{{- define "tarka.containerImage" -}}
{{- $root := index . "root" -}}
{{- $repo := index . "repository" -}}
{{- $tag := index . "tag" -}}
{{- if $root.Values.global.imageRegistry }}
{{- printf "%s/%s:%s" $root.Values.global.imageRegistry $repo $tag }}
{{- else }}
{{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}
