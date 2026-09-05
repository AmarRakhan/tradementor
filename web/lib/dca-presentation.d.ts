export type DcaPresentationInput={runtimeDcaCount?:unknown;positionDcaCount?:unknown;positionDcaCountReliable?:boolean;ladderFilledDcaCount?:unknown;ladderAvailable?:boolean;confirmedFillDcaCount?:unknown;fallbackDcaCount?:unknown;nextDcaNumber?:unknown;nextDcaPrice?:unknown;nextDcaDistancePct?:unknown};
export type DcaPresentation={filledDcaCount:number|null;nextDcaNumber:number|null;nextDcaPrice:number|null;nextDcaDistancePct:number|null;dcaCountReliable:boolean;source:string;mismatch:boolean};
export function deriveDcaPresentation(input?:DcaPresentationInput):DcaPresentation;
