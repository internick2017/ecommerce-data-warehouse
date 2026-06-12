"""GraphQL documents. All use cursor pagination + optional updated_at search filter."""

ORDERS_QUERY = """
query Orders($cursor: String, $query: String) {
  orders(first: 50, after: $cursor, query: $query, sortKey: UPDATED_AT) {
    edges {
      node {
        id
        name
        createdAt
        processedAt
        updatedAt
        currencyCode
        totalPriceSet { shopMoney { amount } }
        subtotalPriceSet { shopMoney { amount } }
        customer { id }
        lineItems(first: 50) {
          edges {
            node {
              id
              title
              quantity
              sku
              product { id }
              originalUnitPriceSet { shopMoney { amount } }
            }
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PRODUCTS_QUERY = """
query Products($cursor: String, $query: String) {
  products(first: 50, after: $cursor, query: $query, sortKey: UPDATED_AT) {
    edges {
      node {
        id
        title
        status
        vendor
        productType
        createdAt
        updatedAt
        variants(first: 50) {
          edges { node { id sku price } }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

CUSTOMERS_QUERY = """
query Customers($cursor: String, $query: String) {
  customers(first: 50, after: $cursor, query: $query, sortKey: UPDATED_AT) {
    edges {
      node {
        id
        displayName
        numberOfOrders
        createdAt
        updatedAt
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ENTITY_QUERIES = {
    "orders": (ORDERS_QUERY, "orders"),
    "products": (PRODUCTS_QUERY, "products"),
    "customers": (CUSTOMERS_QUERY, "customers"),
}
