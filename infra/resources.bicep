// Every ARIA resource, in one resource group. main.bicep creates the group and calls this.

param environmentName string
param location string
param tags object
param principalId string
param principalType string

@secure()
param ariaApiKeys string

@secure()
param pseudonymKey string

@secure()
param nvidiaApiKey string

param deployOpenAi bool
param openAiChatModel string
param openAiChatModelVersion string
param openAiChatCapacity int
param useFreeSqlOffer bool

var token = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
// Until `azd deploy` pushes ARIA's images, the apps run a public placeholder.
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// Built-in role definition ids.
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  cognitiveServicesOpenAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  containerAppsJobsOperator: 'b9a307c4-5aa3-4b52-ba60-2b17c136cd7b'
}

// --- monitoring --------------------------------------------------------------------------------

resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'log-${token}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// --- identity, registry and secrets ------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aria-${token}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${token}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource appPulls 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerPushes 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(registry.id, principalId, roles.acrPush)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
    principalId: principalId
    principalType: principalType
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${token}'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
  }
}

resource apiKeysSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'aria-api-keys'
  properties: {
    value: ariaApiKeys
  }
}

resource pseudonymSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'aria-pseudonym-key'
  properties: {
    value: pseudonymKey
  }
}

resource nvidiaSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(nvidiaApiKey)) {
  parent: vault
  name: 'nvidia-api-key'
  properties: {
    value: nvidiaApiKey
  }
}

resource appReadsSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, roles.keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerManagesSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(vault.id, principalId, roles.keyVaultSecretsOfficer)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsOfficer)
    principalId: principalId
    principalType: principalType
  }
}

// --- Azure SQL: Entra-only authentication, serverless ------------------------------------------

// The app's identity administers the database: it runs the schema migrations on start-up, and
// no SQL password exists anywhere.
resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: 'sql-${token}'
  location: location
  tags: tags
  properties: {
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      login: identity.name
      sid: identity.properties.principalId
      tenantId: tenant().tenantId
      principalType: 'Application'
    }
  }
}

// Lets Azure services, Container Apps among them, reach the server; nothing else can.
resource sqlAllowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource database 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: 'aria'
  location: location
  tags: tags
  sku: {
    name: 'GP_S_Gen5'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 2
  }
  properties: union(
    {
      autoPauseDelay: 60
      minCapacity: json('0.5')
    },
    useFreeSqlOffer
      ? {
          useFreeLimit: true
          freeLimitExhaustionBehavior: 'AutoPause'
        }
      : {}
  )
}

// --- Azure OpenAI (optional) -------------------------------------------------------------------

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (deployOpenAi) {
  name: 'oai-${token}'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: 'oai-${token}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployOpenAi) {
  parent: openAi
  name: openAiChatModel
  sku: {
    name: 'GlobalStandard'
    capacity: openAiChatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: openAiChatModel
      version: openAiChatModelVersion
    }
  }
}

resource appUsesOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployOpenAi) {
  name: guid(resourceGroup().id, identity.id, roles.cognitiveServicesOpenAiUser)
  scope: openAi
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAiUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- Container Apps ----------------------------------------------------------------------------

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var databaseUrl = 'mssql+pyodbc://@${sqlServer.properties.fullyQualifiedDomainName}:1433/${database.name}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no'

var secrets = concat(
  [
    {
      name: 'aria-api-keys'
      keyVaultUrl: apiKeysSecret.properties.secretUri
      identity: identity.id
    }
    {
      name: 'aria-pseudonym-key'
      keyVaultUrl: pseudonymSecret.properties.secretUri
      identity: identity.id
    }
  ],
  empty(nvidiaApiKey)
    ? []
    : [
        {
          name: 'nvidia-api-key'
          keyVaultUrl: '${vault.properties.vaultUri}secrets/nvidia-api-key'
          identity: identity.id
        }
      ]
)

var sharedEnv = concat(
  [
    {
      name: 'ARIA_ENV'
      value: 'prod'
    }
    {
      name: 'ARIA_LOG_FORMAT'
      value: 'json'
    }
    {
      name: 'ARIA_WORKER_MODE'
      value: 'external'
    }
    {
      name: 'ARIA_DATABASE_URL'
      value: databaseUrl
    }
    {
      name: 'ARIA_DATABASE_AUTH'
      value: 'entra'
    }
    {
      name: 'AZURE_CLIENT_ID'
      value: identity.properties.clientId
    }
    {
      name: 'ARIA_OTEL_EXPORTER'
      value: 'azure'
    }
    {
      name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
      value: insights.properties.ConnectionString
    }
    {
      name: 'ARIA_API_KEYS'
      secretRef: 'aria-api-keys'
    }
    {
      name: 'ARIA_PSEUDONYM_KEY'
      secretRef: 'aria-pseudonym-key'
    }
  ],
  empty(nvidiaApiKey)
    ? []
    : [
        {
          name: 'NVIDIA_API_KEY'
          secretRef: 'nvidia-api-key'
        }
      ],
  deployOpenAi
    ? [
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: 'https://oai-${token}.openai.azure.com/openai/v1'
        }
        {
          name: 'AZURE_OPENAI_CHAT_DEPLOYMENT'
          value: openAiChatModel
        }
        {
          name: 'AZURE_OPENAI_USE_ENTRA'
          value: 'true'
        }
      ]
    : []
)

var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${identity.id}': {}
  }
}

var registries = [
  {
    server: registry.properties.loginServer
    identity: identity.id
  }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-api-${token}'
  location: location
  tags: union(tags, {
    'azd-service-name': 'api'
  })
  identity: appIdentity
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: placeholderImage
          env: concat(sharedEnv, [
            {
              name: 'ARIA_MIGRATE_ON_START'
              value: 'true'
            }
            {
              name: 'ARIA_PUBLIC_BASE_URL'
              value: 'https://ca-api-${token}.${environment.properties.defaultDomain}'
            }
          ])
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8000
              }
              periodSeconds: 15
              failureThreshold: 4
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/readyz'
                port: 8000
              }
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Startup'
              httpGet: {
                path: '/healthz'
                port: 8000
              }
              periodSeconds: 10
              failureThreshold: 30 // migrations run before the API listens
            }
          ]
        }
      ]
      // One replica keeps start-up migrations single-file; raise it once a release has migrated.
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    appPulls
    appReadsSecrets
    nvidiaSecret
    sqlAllowAzure
  ]
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-worker-${token}'
  location: location
  tags: union(tags, {
    'azd-service-name': 'worker'
  })
  identity: appIdentity
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: placeholderImage
          env: sharedEnv
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
  dependsOn: [
    appPulls
    appReadsSecrets
    nvidiaSecret
    sqlAllowAzure
  ]
}

// Seeds incident memory and the template history once the API has migrated the database:
//   az containerapp job start -g <resource group> -n <ARIA_SEED_JOB output>
resource seedJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'caj-seed-${token}'
  location: location
  tags: tags
  identity: appIdentity
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'seed'
          image: placeholderImage
          command: [
            'aria'
          ]
          args: [
            'seed'
            '--workers'
            '2'
          ]
          env: sharedEnv
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
        }
      ]
    }
  }
  dependsOn: [
    appPulls
    appReadsSecrets
    nvidiaSecret
  ]
}

resource deployerRunsJobs 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(seedJob.id, principalId, roles.containerAppsJobsOperator)
  scope: seedJob
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.containerAppsJobsOperator)
    principalId: principalId
    principalType: principalType
  }
}

output registryLoginServer string = registry.properties.loginServer
output registryName string = registry.name
output keyVaultName string = vault.name
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output apiName string = api.name
output workerName string = worker.name
output seedJobName string = seedJob.name
