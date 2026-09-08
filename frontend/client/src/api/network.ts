/** DRISHYAM local integration: case-scoped criminal-network read models and relationship review.
 *
 * Every ranked entity arrives with `why` and `caveat` from the server. The interface must render
 * both: a centrality score shown on its own invites the reading that the system is scoring people
 * for criminality, which it is not doing.
 */
import { apiClient } from "./client";

export type NetworkOverviewRecord = { entities: number; relationships: number; communities: number; bridges: number; isolated_entities: number; analytics_version: string };
export type ImportantEntityRecord = { entity_id: string; label: string; entity_type: string; metric: string; score: number; rank: number; connections: number; supporting_evidence_count: number; communities_linked: number; is_bridge: boolean; why: string; caveat: string };
export type NetworkEndpointRecord = { id: string; label: string | null; entity_type?: string | null; type?: string | null };
export type NetworkEdgeRecord = { subject_entity_id: string; object_entity_id: string; relation_types: string[]; confidence: number; observations: number; supporting_evidence_count: number };
export type BridgeRecord = { subject: NetworkEndpointRecord; object: NetworkEndpointRecord; relation_types: string[]; confidence: number; observations: number; supporting_evidence_count: number; why: string; caveat: string };
export type CommunityRecord = { community_id: number; size: number; supporting_evidence_count: number; members: NetworkEndpointRecord[]; caveat: string };
export type NetworkPathRecord = { found: boolean; reason: string | null; nodes: NetworkEndpointRecord[]; edges: NetworkEdgeRecord[]; weakest_link_confidence: number | null; caveat: string | null };
export type NetworkSubgraphRecord = { center: string | null; hops: number | null; nodes: Array<{ id: string; label: string; entity_type: string }>; edges: NetworkEdgeRecord[]; truncated: boolean };

export type EntityRelationRecord = { id: string; relation_type: string; directed: boolean; basis: string; subject: { id: string; label: string | null; type: string | null }; object: { id: string; label: string | null; type: string | null }; source_evidence_id: string; source_record_id: string | null; source_reference: Record<string, unknown>; observed_at: string | null; time_precision: string; confidence: number; verification_status: string; review_note: string | null; created_at: string };
export type EntityRelationPage = { items: EntityRelationRecord[]; total: number; limit: number; offset: number };
export type EntityRelationSummaryRecord = { relation_type: string; meaning: string; directed: boolean; subject: { id: string; label: string | null; type: string | null }; object: { id: string; label: string | null; type: string | null }; observation_ids: string[]; observation_count: number; evidence_ids: string[]; supporting_evidence_count: number; bases: string[]; confidence: number; verification_status: string; first_observed_at: string | null; last_observed_at: string | null };

export type ImportanceMetric = "betweenness_centrality" | "degree_centrality" | "eigenvector_centrality";

const base = (caseId: string) => `/cases/${caseId}/grounded`;

export async function getNetworkOverview(caseId: string): Promise<NetworkOverviewRecord> { return (await apiClient.get(`${base(caseId)}/network/overview`)).data; }
export async function getImportantEntities(caseId: string, params: { metric?: ImportanceMetric; entity_type?: string; min_confidence?: number; verified_only?: boolean; limit?: number } = {}): Promise<ImportantEntityRecord[]> { return (await apiClient.get(`${base(caseId)}/network/important`, { params })).data; }
export async function getNetworkBridges(caseId: string, minConfidence = 0): Promise<BridgeRecord[]> { return (await apiClient.get(`${base(caseId)}/network/bridges`, { params: { min_confidence: minConfidence } })).data; }
export async function getNetworkCommunities(caseId: string, minConfidence = 0): Promise<CommunityRecord[]> { return (await apiClient.get(`${base(caseId)}/network/communities`, { params: { min_confidence: minConfidence } })).data; }
export async function getNetworkPath(caseId: string, sourceEntityId: string, targetEntityId: string): Promise<NetworkPathRecord> { return (await apiClient.get(`${base(caseId)}/network/path`, { params: { source_entity_id: sourceEntityId, target_entity_id: targetEntityId } })).data; }
export async function getNetworkSubgraph(caseId: string, entityId: string, hops = 1): Promise<NetworkSubgraphRecord> { return (await apiClient.get(`${base(caseId)}/network/subgraph`, { params: { entity_id: entityId, hops } })).data; }

export async function getEntityRelations(caseId: string, params: { relation_type?: string; entity_id?: string; verification_status?: string; limit?: number; offset?: number } = {}): Promise<EntityRelationPage> { return (await apiClient.get(`${base(caseId)}/entity-relations`, { params })).data; }
export async function getEntityRelationSummary(caseId: string): Promise<EntityRelationSummaryRecord[]> { return (await apiClient.get(`${base(caseId)}/entity-relations/summary`)).data; }
export async function reviewEntityRelation(caseId: string, relationId: string, action: "confirm_relationship" | "reject_relationship", reason?: string): Promise<EntityRelationRecord> { return (await apiClient.post(`${base(caseId)}/entity-relations/${relationId}/review`, { action, reason })).data; }
