{{- define "tarka.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "tarka.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "tarka.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "tarka.image" -}}
{{- $registry := .registry | default "" -}}
{{- $image := .image -}}
{{- $tag := .tag | default "latest" -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $image $tag -}}
{{- else -}}
{{- printf "%s:%s" $image $tag -}}
{{- end -}}
{{- end }}
