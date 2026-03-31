{{- define "tarka.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "tarka.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "tarka.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
