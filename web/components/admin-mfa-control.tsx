"use client";

import {useEffect,useState} from "react";
import QRCode from "qrcode";
import {authenticatedRequest} from "@/lib/cloud-client";

type Props={allowed:boolean;configured:boolean;onAllowed:(allowed:boolean,configured:boolean)=>void};

export function AdminMfaControl({allowed,configured,onAllowed}:Props){
  const [open,setOpen]=useState(false);const [code,setCode]=useState("");const [qr,setQr]=useState("");
  const [manualKey,setManualKey]=useState("");const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
  const [recoveryCodes,setRecoveryCodes]=useState<string[]>([]);
  useEffect(()=>{if(!open){setCode("");setQr("");setManualKey("");setMessage("")}},[open]);

  async function begin(){
    setBusy(true);setMessage("");setOpen(true);
    try{const value=await authenticatedRequest("/api/admin/mfa/setup",{method:"POST"});
      if(value.otpauthUri){setManualKey(String(value.manualKey||""));setQr(await QRCode.toDataURL(String(value.otpauthUri),{width:240,margin:2,errorCorrectionLevel:"M"}));}
    }catch(reason){setMessage(reason instanceof Error?reason.message:"Authenticator starten is niet gelukt.")}
    finally{setBusy(false)}
  }

  async function verify(){
    if(code.trim().length<6)return;setBusy(true);setMessage("");
    const deviceId=window.localStorage.getItem("tradementor.admin.device.v2")||`${crypto.randomUUID()}-${crypto.randomUUID()}`;
    window.localStorage.setItem("tradementor.admin.device.v2",deviceId);
    try{const value=await authenticatedRequest("/api/admin/device/verify",{method:"POST",body:JSON.stringify({device_id:deviceId,device_label:navigator.userAgent.slice(0,220),code,confirm:true})});
      window.localStorage.setItem("tradementor.admin.credential.v2",String(value.credential));setRecoveryCodes(Array.isArray(value.recoveryCodes)?value.recoveryCodes:[]);
      onAllowed(true,true);setMessage("Beheerder is op dit toestel voor 12 uur geactiveerd.");
    }catch(reason){setMessage(reason instanceof Error?reason.message:"De verificatie is niet gelukt.")}
    finally{setBusy(false)}
  }

  function deactivate(){window.localStorage.removeItem("tradementor.admin.credential.v2");onAllowed(false,true);setOpen(false);setMessage("Beheerder is op dit toestel uitgeschakeld.")}

  return <section className="admin-device-setting"><span className="kicker">BEVEILIGD BEHEER</span>
    <strong>{allowed?"Beheerder actief":configured?"Google Authenticator vereist":"Authenticator nog instellen"}</strong>
    <p>Alleen het adminaccount kan dit starten. Ieder toestel moet afzonderlijk met Google Authenticator worden bevestigd.</p>
    {allowed?<button type="button" onClick={deactivate}>Beheerder uitschakelen</button>:<button type="button" onClick={begin} disabled={busy}>{configured?"Beheerder activeren":"Google Authenticator instellen"}</button>}
    {open&&!allowed&&<div className="admin-mfa-panel">
      {qr&&<><img src={qr} alt="QR-code voor Google Authenticator"/><p>Scan deze QR-code in Google Authenticator. Handmatig: <code>{manualKey}</code></p></>}
      <label>Authenticator- of herstelcode<input value={code} onChange={event=>setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456"/></label>
      <button type="button" onClick={verify} disabled={busy||code.trim().length<6}>Veilig bevestigen</button>
    </div>}
    {recoveryCodes.length>0&&<div className="admin-recovery-codes"><strong>Bewaar deze eenmalige herstelcodes veilig</strong><p>Ze worden hierna niet opnieuw getoond.</p><code>{recoveryCodes.join("\n")}</code></div>}
    {message&&<small>{message}</small>}
  </section>
}
