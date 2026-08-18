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
{{- $digest := .digest | default "" -}}
{{- $name := $image -}}
{{- if $registry -}}
{{- $name = printf "%s/%s" $registry $image -}}
{{- end -}}
{{- if $digest -}}
{{- printf "%s@%s" $name $digest -}}
{{- else -}}
{{- printf "%s:%s" $name $tag -}}
{{- end -}}
{{- end }}
