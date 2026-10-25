// Reuses the existing document containers, queue, storage account and Function App.
// Creates the Flex deployment package container if it does not already exist.
// Reuses the existing Flex Consumption Function App; it does not create or reconfigure the app.

@description('Name of the existing Flex Consumption Function App in this resource group.')
param functionAppName string = 'func-b2s-setowq66u6xfi'

@description('Name of the existing storage account that contains the bronze and silver containers.')
param storageAccountName string = 'corpordrage'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource bronze 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blobService
  name: 'bronze'
}

resource silver 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blobService
  name: 'silver'
}

resource deployments 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'app-packages'
  properties: { publicAccess: 'None' }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource documentQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' existing = {
  parent: queueService
  name: 'bronze-to-silver'
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionAppName
}

output functionAppName string = functionApp.name
output storageAccountName string = storageAccount.name
output bronzeContainerName string = bronze.name
output silverContainerName string = silver.name
output documentQueueName string = documentQueue.name
