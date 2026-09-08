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

{{- define "tarka.apiKeyTenantMapOptional" -}}
{{- if eq (default "dev" .Values.global.environment) "prod" -}}
false
{{- else -}}
true
{{- end -}}
{{- end }}

{{- define "tarka.helmEnvironment" -}}
{{- default "dev" .Values.global.environment -}}
{{- end }}

{{- /* Same prod gate as validate-prod.yaml: environment=prod or TARKA_DEPLOYMENT_PROFILE=production. */ -}}
{{- define "tarka.prodProfile" -}}
{{- $extraEnv := ((.Values.coreApi).extraEnv | default dict) -}}
{{- $deployProfile := "" -}}
{{- if hasKey $extraEnv "TARKA_DEPLOYMENT_PROFILE" -}}
{{- $deployProfile = lower (trim (toString (index $extraEnv "TARKA_DEPLOYMENT_PROFILE"))) -}}
{{- end -}}
{{- if or (eq (include "tarka.helmEnvironment" .) "prod") (eq $deployProfile "production") -}}
true
{{- else -}}
false
{{- end -}}
{{- end }}

{{- /* Explicit opt-out. Boolean enabled wins; null/unset follows prodProfile. */ -}}
{{- define "tarka.networkPolicy.enabled" -}}
{{- $cfg := ((.Values.global).networkPolicy | default dict) -}}
{{- if and (hasKey $cfg "enabled") (kindIs "bool" $cfg.enabled) -}}
{{- if $cfg.enabled }}true{{ else }}false{{ end -}}
{{- else -}}
{{- include "tarka.prodProfile" . -}}
{{- end -}}
{{- end }}

{{- define "tarka.serviceMonitor.enabled" -}}
{{- $cfg := ((.Values.global).serviceMonitor | default dict) -}}
{{- if and (hasKey $cfg "enabled") (kindIs "bool" $cfg.enabled) -}}
{{- if $cfg.enabled }}true{{ else }}false{{ end -}}
{{- else -}}
{{- include "tarka.prodProfile" . -}}
{{- end -}}
{{- end }}
