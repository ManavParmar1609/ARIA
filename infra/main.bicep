// ARIA on Azure: Container Apps (api, worker, seed job), Azure SQL (Entra-only, serverless),
// Key Vault, Container Registry, Log Analytics and Application Insights, one user-assigned
// managed identity, and optionally Azure OpenAI. Deployed with `azd up` (see azure.yaml).
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('Name of the azd environment; it names the resource group and tags every resource.')
param environmentName string

@minLength(1)
@description('Azure region for every resource.')
param location string

@description('Object id of the user or service principal running the deployment (azd sets it). It may push images, read and write Key Vault secrets and start the seed job.')
param principalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
])
@description('Kind of principal in principalId: a person running azd, or a CI service principal.')
param principalType string = 'User'

@secure()
@description('API keys the service accepts (ARIA_API_KEYS): comma-separated name:secret pairs.')
param ariaApiKeys string

@secure()
@description('Key for pseudonymising IPs and e-mail addresses in logs (ARIA_PSEUDONYM_KEY).')
param pseudonymKey string

@secure()
@description('NVIDIA API key for hosted NIM (build.nvidia.com). Leave empty to run without NIM.')
param nvidiaApiKey string = ''

@description('Deploy an Azure OpenAI account and a chat deployment as another LLM provider.')
param deployOpenAi bool = false

@description('Azure OpenAI chat model to deploy, as listed for your region in the Azure portal.')
param openAiChatModel string = ''

@description('Version of that model, as listed in the Azure portal (model versions change often).')
param openAiChatModelVersion string = ''

@description('Capacity of the chat deployment, in thousands of tokens per minute.')
param openAiChatCapacity int = 10

@description('Use the Azure SQL Database free offer (one per subscription); pauses when used up.')
param useFreeSqlOffer bool = true

var tags = {
  'azd-env-name': environmentName
  app: 'aria'
}

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'aria-resources'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    principalId: principalId
    principalType: principalType
    ariaApiKeys: ariaApiKeys
    pseudonymKey: pseudonymKey
    nvidiaApiKey: nvidiaApiKey
    deployOpenAi: deployOpenAi
    openAiChatModel: openAiChatModel
    openAiChatModelVersion: openAiChatModelVersion
    openAiChatCapacity: openAiChatCapacity
    useFreeSqlOffer: useFreeSqlOffer
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.registryName
output AZURE_KEY_VAULT_NAME string = resources.outputs.keyVaultName
output AZURE_SQL_SERVER string = resources.outputs.sqlServerFqdn
output SERVICE_API_ENDPOINT_URL string = resources.outputs.apiUrl
output SERVICE_API_NAME string = resources.outputs.apiName
output SERVICE_WORKER_NAME string = resources.outputs.workerName
output ARIA_SEED_JOB string = resources.outputs.seedJobName
