/**
 * Temporary frontend rollout rule. The catalog currently has no dedicated
 * "released" field, so only the canonical Pedidos module is customer-visible.
 */
export const isReleasedModule = (module) => module?.key === "orders";
