// The Gallery: Azure infrastructure (deploy with `azd up`).
// Everything is keyless: the app's user-assigned managed identity gets RBAC roles on
// Foundry, Event Hubs, Cosmos DB and the container registry.
targetScope = 'resourceGroup'

@description('Short environment name, used to make resource names unique.')
param environmentName string

@description('Region for the new resources.')
param location string = resourceGroup().location

@description('Name of the existing Microsoft Foundry (AIServices) resource in this resource group.')
param foundryResourceName string = 'gallery-foundry-sb'

@description('Name of the Foundry project inside that resource.')
param foundryProjectName string = 'the-gallery'

@description('Model deployment used by the agents.')
param fastModel string = 'gpt-5.4-mini'

@description('Model deployment used by the Storyteller and recap writer.')
param creativeModel string = 'gpt-5.4-mini'

@description('Container image set by azd after the remote build.')
param webImageName string = ''

var token = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var tags = { 'azd-env-name': environmentName, project: 'the-gallery' }

// Built-in role definition ids
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  azureAIDeveloper: '64702f94-c441-49e6-a78b-ef80e0188fee'
  eventHubsDataOwner: 'f526a384-b230-433a-b45c-95f59c4a2dec'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-gallery-${token}'
  location: location
  tags: tags
}

// ---------------------------------------------------------------- observability
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-gallery-${token}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-gallery-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ---------------------------------------------------------------- registry
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crgallery${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- streaming
resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evh-gallery-${token}'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  properties: { disableLocalAuth: true }
}

resource matchEvents 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubs
  name: 'match-events'
  properties: {
    partitionCount: 2
    messageRetentionInDays: 1
  }
}

resource matchRoomGroup 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: matchEvents
  name: 'match-room'
}

resource ehOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(eventHubs.id, identity.id, roles.eventHubsDataOwner)
  scope: eventHubs
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsDataOwner)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- storage of insights
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-gallery-${token}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0 } ]
    capabilities: [ { name: 'EnableServerless' } ]
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'gallery'
  properties: { resource: { id: 'gallery' } }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'insights'
  properties: {
    resource: {
      id: 'insights'
      partitionKey: { paths: [ '/match_id' ], kind: 'Hash' }
    }
  }
}

resource cosmosWriter 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, 'data-contributor')
  properties: {
    // Cosmos DB Built-in Data Contributor
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: identity.properties.principalId
    scope: cosmos.id
  }
}

// ---------------------------------------------------------------- Foundry access
resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryResourceName
}

resource foundryRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in [
  roles.cognitiveServicesOpenAIUser
  roles.cognitiveServicesUser
  roles.azureAIDeveloper
]: {
  name: guid(foundry.id, identity.id, r)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

// ---------------------------------------------------------------- the app
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-gallery-${token}'
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

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-gallery-${token}'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [ acrPull ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: empty(webImageName) ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' : webImageName
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'AZURE_AI_PROJECT_ENDPOINT', value: 'https://${foundryResourceName}.services.ai.azure.com/api/projects/${foundryProjectName}' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://${foundryResourceName}.openai.azure.com/openai/v1' }
            { name: 'GALLERY_FAST_MODEL', value: fastModel }
            { name: 'GALLERY_CREATIVE_MODEL', value: creativeModel }
            { name: 'GALLERY_LANGUAGES', value: 'en,hi,es' }
            { name: 'GALLERY_ANALYST_VIA_MCP', value: '1' }
            { name: 'EVENTHUB_NAMESPACE', value: '${eventHubs.name}.servicebus.windows.net' }
            { name: 'EVENTHUB_NAME', value: matchEvents.name }
            { name: 'EVENTHUB_CONSUMER_GROUP', value: matchRoomGroup.name }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'SPEECH_REGION', value: foundry.location }
            { name: 'SPEECH_RESOURCE_ID', value: foundry.id }
            { name: 'PORT', value: '8000' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
          ]
        }
      ]
      // One replica: each match room keeps its live state in memory.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output SERVICE_WEB_NAME string = app.name
output SERVICE_WEB_URI string = 'https://${app.properties.configuration.ingress.fqdn}'
output EVENTHUB_NAMESPACE string = '${eventHubs.name}.servicebus.windows.net'
output COSMOS_ENDPOINT string = cosmos.properties.documentEndpoint
output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.properties.ConnectionString
