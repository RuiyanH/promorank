export interface V2Item {
  position:number; article_id:string; ordering_score:number;
  source_evidence:{source:string;display_name:string;source_rank:number}[];
  article_metadata:{product_type_name:string|null;metadata_status:string};
}
export interface V2Recommendations {
  schema_version:"workbench-api.v2";release_id:string;as_of:string;ranking_mode:"trained_ranker";
  score_semantics:"ordering_only";warning:string;model_available_after:string;calibrator_available_after:string;
  customer_ref:string;recommendations:V2Item[];
}
export interface CustomerPage { schema_version:"workbench-customers.v2";release_id:string;customers:{customer_ref:string;display_label:string}[];next_cursor:string|null }
export function validateRecommendations(value:unknown):V2Recommendations;
export function validateCustomers(value:unknown):CustomerPage;
export interface ReplayRelease {release_id:string;status:"candidate"|"verified";dates:string[];customer_count:number;warning:string;model_available_after:string;calibrator_available_after:string}
export function validateReleases(value:unknown):{schema_version:"workbench-releases.v2";releases:ReplayRelease[]};
export function validateQuality(value:unknown):Record<string,unknown>;
export function replayEnabled():boolean;
export function subscribeReplayMode(notify:()=>void):()=>void;
export function serverReplayMode():boolean;
export function requestReplay(path:string, signal?:AbortSignal):Promise<unknown>;
export function readLocalReviews(release:string,day:string,customer:string):Record<string,"relevant"|"not_relevant">;
export function saveLocalReview(release:string,day:string,customer:string,article:string,signal:"relevant"|"not_relevant"|null):void;
