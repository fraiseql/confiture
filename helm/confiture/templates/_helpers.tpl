{{/*
Expand the name of the chart.
*/}}
{{- define "confiture.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "confiture.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "confiture.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "confiture.labels" -}}
helm.sh/chart: {{ include "confiture.chart" . }}
{{ include "confiture.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "confiture.selectorLabels" -}}
app.kubernetes.io/name: {{ include "confiture.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "confiture.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "confiture.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the image name
*/}}
{{- define "confiture.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/*
Create the database URL from components
*/}}
{{- define "confiture.databaseUrl" -}}
{{- $host := .Values.database.host }}
{{- $port := .Values.database.port }}
{{- $name := .Values.database.name }}
{{- $user := .Values.database.user }}
{{- $sslMode := .Values.database.sslMode }}
{{- printf "postgresql://%s:$(DB_PASSWORD)@%s:%d/%s?sslmode=%s" $user $host (int $port) $name $sslMode }}
{{- end }}

{{/*
Determine if we need to create a database secret
*/}}
{{- define "confiture.createDatabaseSecret" -}}
{{- if and (not .Values.database.existingSecret) .Values.database.passwordSecret }}
{{- true }}
{{- end }}
{{- end }}
