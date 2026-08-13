package com.tradementor.app.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.cloud.MexcCloudClient
import com.tradementor.app.cloud.MexcCloudStatus
import com.tradementor.app.mexc.*
import com.tradementor.app.security.MexcCredentialVault
import kotlinx.coroutines.launch
import java.util.Locale
import java.util.UUID

private val mexcGreen=Color(0xFF19D69A); private val mexcBlue=Color(0xFF4BB8FF); private val mexcMuted=Color(0xFF95A2B6)

@Composable fun MexcAutoTradeScreen(){
    val context=androidx.compose.ui.platform.LocalContext.current; val scope=rememberCoroutineScope(); val client=remember{MexcMarketClient()}
    var settings by remember{mutableStateOf(MexcPaperStore.settings(context))}; var session by remember{mutableStateOf(MexcPaperStore.session(context))}; var market by remember{mutableStateOf(MexcMarketSnapshot())}; var cloudStatus by remember{mutableStateOf(MexcCloudStatus())}; var settingsOpen by remember{mutableStateOf(false)}; var message by remember{mutableStateOf("")}; var backtest by remember{mutableStateOf<MexcBacktestResult?>(null)}; var busy by remember{mutableStateOf(false)}; var connectOpen by remember{mutableStateOf(false)}
    suspend fun refresh(){runCatching{market=client.snapshot()}.onFailure{message=it.message.orEmpty()}}
    suspend fun refreshCloud(){runCatching{cloudStatus=MexcCloudClient.status()}.onFailure{message=it.message.orEmpty()}}
    LaunchedEffect(Unit){
        refresh()
        refreshCloud()
        if (!cloudStatus.configured && MexcCredentialVault.configured(context)) {
            runCatching {
                val (key, secret) = MexcCredentialVault.read(context)
                MexcCloudClient.connect(key, secret)
            }.onSuccess {
                cloudStatus = it
                message = "Bestaande MEXC-koppeling veilig naar jouw persoonlijke cloud gekopieerd en gecontroleerd. De lokale kopie blijft versleuteld bewaard."
            }.onFailure {
                message = "MEXC-cloudmigratie: ${it.message.orEmpty()}"
            }
        }
    }
    LaunchedEffect(session?.closed,settings.mode,settings.executionTimeframe,settings.riskTimeframe){
        while(session!=null && session?.closed==false && settings.mode==MexcMode.PAPER){
            runCatching{
                val execution=client.candles(settings.executionTimeframe,30)
                val risk=client.candles(settings.riskTimeframe,60)
                val point=MexcSignalCalculator.point(execution,risk)
                val current=session ?: return@runCatching
                val next=MexcAdaptiveEngine.executePaper(settings,current,point,MexcAdaptiveEngine.decide(settings,current,point,exchangeMinimumNotional=market.minimumNotional))
                session=next; MexcPaperStore.saveSession(context,next); market=client.snapshot()
            }.onFailure{message="Paper-monitor: ${it.message.orEmpty()}"}
            kotlinx.coroutines.delay(15_000)
        }
    }
    LaunchedEffect(settings.mode){
        while(settings.mode==MexcMode.LIVE){
            refreshCloud()
            refresh()
            kotlinx.coroutines.delay(5_000)
        }
    }
    val liveDashboard = remember(cloudStatus){MexcLiveSessionMapper.from(cloudStatus)}
    val displayedSession = if(settings.mode==MexcMode.LIVE) liveDashboard?.session else session
    Column(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color(0xFF06101A),Color(0xFF03060B)))).verticalScroll(rememberScrollState()).padding(16.dp)){
        Row(verticalAlignment=Alignment.CenterVertically){Column(Modifier.weight(1f)){Text("AUTO TRADE",color=Color.White,fontSize=27.sp,fontWeight=FontWeight.Bold);Text("MEXC FUTURES · BTC_USDT · HEDGE MODE",color=mexcBlue,fontSize=11.sp)};Button(onClick={settingsOpen=!settingsOpen}){Text(if(settingsOpen)"DASHBOARD" else "SETTINGS")}}
        Spacer(Modifier.height(12.dp)); StatusPanel(market,settings,session,cloudStatus)
        if(settingsOpen) MexcSettingsPanel(settings,cloudStatus.credentialsVerified,{settings=it;MexcPaperStore.saveSettings(context,it)},onConnect={connectOpen=true}) else MexcDashboard(settings,displayedSession,market,backtest,cloudStatus,liveDashboard,busy,onStart={
            val errors=MexcAdaptiveEngine.validateV3(settings)
            when {
                errors.isNotEmpty() -> message=errors.joinToString("\n")
                settings.mode==MexcMode.LIVE -> scope.launch {
                    busy=true
                    if(cloudStatus.executionLeverage!=MexcAdaptiveEngine.FIXED_LEVERAGE || !cloudStatus.executionMarginMode.equals("cross",true)){
                        message="VEILIG GEBLOKKEERD · cloudprofiel Cross 200× is nog niet gepubliceerd"
                    } else if(cloudStatus.liveEnabled && cloudStatus.ordersEnabled){
                        runCatching{MexcCloudClient.startAutomation(settings)}
                            .onSuccess{result->message=if(result.automationPaused)"AUTOMATISERING GEPAUZEERD · ${result.automationPauseReason}" else "AUTOMATISCHE MEXC-HANDEL ACTIEF · Cross 200× · cloudcontrole iedere minuut";refreshCloud()}
                            .onFailure{message=it.message.orEmpty()}
                    } else {
                        runCatching{MexcCloudClient.setLive(true,true)}.onSuccess{cloudStatus=it;message=if(it.ordersEnabled)"MEXC LIVE is geactiveerd. Controleer de limiet en druk nogmaals voor de eenmalige $8,50-canary." else "MEXC-account is gecontroleerd. Orderuitvoering blijft centraal vergrendeld."}.onFailure{message=it.message.orEmpty()}
                    }
                    busy=false
                }
                else -> { val eq=settings.paperEquity; session=MexcSession(eq,eq,eq); MexcPaperStore.saveSession(context,session!!); message="Papersessie gestart" }
            }
        },onStop={if(settings.mode==MexcMode.LIVE)scope.launch{busy=true;runCatching{MexcCloudClient.stopAutomation()}.onSuccess{message="AUTOMATISERING GESTOPT · geen nieuwe exposure; bestaande positie blijft beschermd";refreshCloud()}.onFailure{message=it.message.orEmpty()};busy=false}else{MexcPaperStore.clearSession(context);session=null;message="Papersessie gestopt"}},onBacktest={scope.launch{busy=true;runCatching{val execution=client.candles(settings.executionTimeframe,600);val risk=client.candles(settings.riskTimeframe,600);MexcBacktester.run(settings.copy(mode=MexcMode.PAPER),execution,risk,market.maintenanceMarginRate.takeIf{it>0}?:.001,market.liquidationFeeRate.takeIf{it>0}?:.0004)}.onSuccess{backtest=it;message="Backtest afgerond: DCA ${settings.executionTimeframe}, hedge ${settings.riskTimeframe}; geen orders"}.onFailure{message=it.message.orEmpty()};busy=false}})
        if(message.isNotBlank())Text(message,color=if(message.contains("fout",true))Color(0xFFFF647C) else mexcMuted,fontSize=12.sp,modifier=Modifier.padding(vertical=10.dp))
    }
    if(connectOpen) MexcConnectDialog(onClose={connectOpen=false},onSave={key,secret->scope.launch{busy=true;MexcCredentialVault.save(context,key,secret);runCatching{MexcCloudClient.connect(key,secret)}.onSuccess{cloudStatus=it;connectOpen=false;message="MEXC-account, Futures-saldo en hedge mode zijn door de persoonlijke cloud gecontroleerd."}.onFailure{message=it.message.orEmpty()};busy=false}})
}

@Composable private fun StatusPanel(market:MexcMarketSnapshot,s:MexcSettings,session:MexcSession?,cloud:MexcCloudStatus)=Surface(color=Color(0xDD0C1724),shape=RoundedCornerShape(20.dp)){Column(Modifier.padding(15.dp)){Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Text("MEXC ${if(cloud.credentialsVerified)"CLOUD GECONTROLEERD" else "NIET GECONTROLEERD"}",color=if(cloud.credentialsVerified)mexcGreen else Color(0xFFFFB84D),fontWeight=FontWeight.Bold);Text(if(s.mode==MexcMode.PAPER)"PAPER" else "REAL MONEY",color=if(s.mode==MexcMode.PAPER)mexcBlue else Color(0xFFFF5572),fontWeight=FontWeight.Bold)};Row(Modifier.fillMaxWidth().padding(top=12.dp),horizontalArrangement=Arrangement.SpaceBetween){Metric("BTC",if(market.connected)usd(market.price) else "laden");Metric(if(s.mode==MexcMode.LIVE)"EQUITY" else "SESSION",usd(if(s.mode==MexcMode.LIVE)cloud.equity else session?.startEquity?:s.paperEquity));Metric(if(s.mode==MexcMode.LIVE)"AVAILABLE" else "CURRENT",usd(if(s.mode==MexcMode.LIVE)cloud.availableOpen else session?.currentEquity?:s.paperEquity));Metric(if(s.mode==MexcMode.LIVE)"MARGIN" else "LOWEST",usd(if(s.mode==MexcMode.LIVE)cloud.positionMargin else session?.lowestEquity?:s.paperEquity))};if(cloud.credentialsVerified)Text("Hedge mode ${if(cloud.hedgeMode)"OK" else "VEREIST"} · BTC-posities ${cloud.openBtcPositions} · account max ${cloud.maximumLeverage}x · key …${cloud.keySuffix}",color=if(cloud.liveReady)mexcGreen else Color(0xFFFFB84D),fontSize=10.sp,modifier=Modifier.padding(top=8.dp));if(market.connected)Text("MEXC minimum nu ${usd(market.minimumNotional)} notional · contract max ${market.maximumLeverage}x",color=mexcMuted,fontSize=10.sp,modifier=Modifier.padding(top=4.dp))}}

@Composable private fun MexcDashboard(s:MexcSettings,session:MexcSession?,market:MexcMarketSnapshot,backtest:MexcBacktestResult?,cloud:MexcCloudStatus,live:MexcLiveDashboardState?,busy:Boolean,onStart:()->Unit,onStop:()->Unit,onBacktest:()->Unit){
    val long=cloud.positions.firstOrNull{it.side.equals("long",true)}
    val short=cloud.positions.firstOrNull{it.side.equals("short",true)}
    val longNotional=if(s.mode==MexcMode.LIVE)long?.notionalUsd?:0.0 else session?.longNotional?:0.0
    val shortNotional=if(s.mode==MexcMode.LIVE)short?.notionalUsd?:0.0 else session?.shortNotional?:0.0
    val equity=if(s.mode==MexcMode.LIVE)cloud.equity else session?.currentEquity?:s.paperEquity
    val walletBalance=if(s.mode==MexcMode.LIVE)cloud.availableBalance+cloud.positionMargin else session?.startEquity?:s.paperEquity
    Section("TEST 3 · HEDGE DCA"){
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("WALLET",usd(walletBalance));Metric("EQUITY",usd(equity));Metric("AVAILABLE",usd(if(s.mode==MexcMode.LIVE)cloud.availableOpen else equity));Metric("UNREALIZED",usd(if(s.mode==MexcMode.LIVE)cloud.unrealizedPnl else 0.0))}
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("LONG",usd(longNotional));Metric("SHORT",usd(shortNotional));Metric("NET EXPOSURE",usd(longNotional-shortNotional));Metric("FEES",usd(cloud.automationFees))}
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("LONG AVG",usd(long?.entryPrice?:0.0));Metric("LONG TP",usd((long?.entryPrice?:0.0)*(1+s.takeProfit)));Metric("DCA LONG",cloud.automationLongDcaCount.toString());Metric("DCA SHORT",cloud.automationShortDcaCount.toString())}
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("SHORT AVG",usd(short?.entryPrice?:0.0));Metric("SHORT TP",usd((short?.entryPrice?:0.0)*(1-s.takeProfit)));Metric("EMERGENCY",usd(s.emergencyEquityTrigger));Metric("AFSTAND",usd(equity-s.emergencyEquityTrigger))}
        Text("STATE · ${cloud.automationPhase} · ${cloud.automationReason}",color=if(cloud.automationFrozen)Color(0xFFFFC857) else mexcGreen,fontWeight=FontWeight.Bold,modifier=Modifier.padding(top=12.dp))
        if(cloud.automationFrozen)Text("FROZEN · DELTA NEUTRAL",color=Color(0xFFFFC857),fontSize=18.sp,fontWeight=FontWeight.Black)
        if(cloud.automationRescueState.isNotBlank())Text("RESCUE · ${cloud.automationRescueState}",color=mexcBlue,fontWeight=FontWeight.Bold)
        Text("Iedere kant: ${usd(s.initialOrderNotional)} notional · TP ${pct(s.takeProfit*100)} · max ${s.maximumDcaOrders} DCA · Cross 200×",color=mexcMuted,fontSize=11.sp,modifier=Modifier.padding(top=8.dp))
        val control=mexcAutomationControlState(s.mode,session!=null&&session.closed==false,cloud.automationEnabled,cloud.automationMonitoring,cloud.automationProtectiveOnly)
        if(control.protectiveMonitoring)Text("BESCHERMING ACTIEF · geen nieuwe exposure · START hervat alleen na jouw bevestiging",color=Color(0xFFFFC857),fontSize=11.sp,fontWeight=FontWeight.Bold,modifier=Modifier.padding(top=10.dp))
        Row(Modifier.fillMaxWidth().padding(top=12.dp),horizontalArrangement=Arrangement.spacedBy(8.dp)){
            val stopping=control.primaryAction==MexcAutomationPrimaryAction.STOP
            Button(if(stopping)onStop else onStart,Modifier.weight(1f),enabled=!busy){Text(if(busy)"CONTROLEREN..." else if(stopping)"STOP AUTOMATISERING" else if(s.mode==MexcMode.LIVE)"START V3 LIVE" else "START PAPER")}
            OutlinedButton(onBacktest,Modifier.weight(1f),enabled=!busy){Text(if(busy)"TESTEN..." else "SIMULEER V3")}
        }
    }
    val ratio=(live?.marginRatioPercent?:0.0).coerceIn(0.0,100.0)
    val riskColor=when{ratio<25->mexcGreen;ratio<60->Color(0xFFFFC857);else->Color(0xFFFF5572)}
    Section("LIQUIDATIEMONITOR"){
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Text("MARGIN RATIO",color=Color.White,fontWeight=FontWeight.Bold);Text(pct(ratio),color=riskColor,fontSize=24.sp,fontWeight=FontWeight.Black)}
        LinearProgressIndicator(progress={ratio.toFloat()/100f},modifier=Modifier.fillMaxWidth().height(10.dp),color=riskColor,trackColor=Color(0xFF223044))
        Text("0% veilig · 100% liquidatie · noodrem kijkt naar EQUITY ${usd(equity)}",color=mexcMuted,fontSize=11.sp,modifier=Modifier.padding(top=8.dp))
    }
}

@Composable private fun MexcLegacyDashboard(s:MexcSettings,session:MexcSession?,market:MexcMarketSnapshot,backtest:MexcBacktestResult?,cloud:MexcCloudStatus,live:MexcLiveDashboardState?,busy:Boolean,onStart:()->Unit,onStop:()->Unit,onBacktest:()->Unit){
    val eq=if(s.mode==MexcMode.LIVE)cloud.automationSessionStartEquity.takeIf{it>0}?:cloud.equity else session?.startEquity?:s.paperEquity
    Section("LIVE SESSIE"){
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("LONG",usd(session?.longNotional?:0.0));Metric("SHORT HEDGE",usd(session?.shortNotional?:0.0));Metric("NET EXPOSURE",usd(session?.netExposure?:0.0));Metric("OPEN PNL",usd(live?.unrealizedPnl?:0.0))}
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("AVG ENTRY",usd(session?.weightedEntry?:0.0));Metric("TP PRICE",usd((session?.weightedEntry?:0.0)*(1+s.takeProfit)));Metric("DCA",(if(s.mode==MexcMode.LIVE)cloud.automationDcaCount else session?.dcaCount?:0).toString());Metric("HEFBOOM",cloud.positions.firstOrNull()?.leverage?.let{"${it}x"}?:"200x")}
        Spacer(Modifier.height(10.dp))
        Text(if(s.mode==MexcMode.LIVE)"Cloudfase: ${cloud.automationPhase} · ${cloud.automationReason}" else "Fase: ${session?.phase?:MexcPhase.WAIT} · ${session?.reason?:"Nog niet gestart"}",color=if(cloud.automationPaused)Color(0xFFFF5572) else Color.White)
        if(cloud.automationPaused)Text("VEILIG GEPAUZEERD · ${cloud.automationPauseReason}",color=Color(0xFFFF5572),fontWeight=FontWeight.Bold)
        if(s.mode==MexcMode.LIVE)Row(Modifier.fillMaxWidth().padding(top=10.dp),horizontalArrangement=Arrangement.SpaceBetween){Metric("RISK",cloud.automationRiskScore.toString());Metric("RECOVERY",cloud.automationRecoveryScore.toString());Metric("NET SESSION",usd(cloud.automationNetSessionPnl));Metric("FEES",usd(cloud.automationFees))}
        Text("Eerste order ${usd(MexcAdaptiveEngine.initialNotional(s,eq))} notional · Veilige max Long ${usd(MexcAdaptiveEngine.safeMaximumLong(s,eq))} · Hedge-trigger -${usd(MexcAdaptiveEngine.hedgeTriggerUsd(s,eq))}",color=mexcMuted,fontSize=11.sp)
        val control=mexcAutomationControlState(s.mode,session!=null&&session.closed==false,cloud.automationEnabled,cloud.automationMonitoring,cloud.automationProtectiveOnly)
        if(control.protectiveMonitoring)Text("BESCHERMING ACTIEF · geen nieuwe exposure · START hervat alleen na jouw bevestiging",color=Color(0xFFFFC857),fontSize=11.sp,fontWeight=FontWeight.Bold,modifier=Modifier.padding(top=10.dp))
        Row(Modifier.fillMaxWidth().padding(top=12.dp),horizontalArrangement=Arrangement.spacedBy(8.dp)){
            val stopping=control.primaryAction==MexcAutomationPrimaryAction.STOP
            Button(if(stopping)onStop else onStart,Modifier.weight(1f),enabled=!busy){Text(if(busy)"CONTROLEREN..." else if(stopping)"STOP AUTOMATISERING" else if(s.mode==MexcMode.PAPER)"START PAPER" else if(cloud.liveEnabled&&cloud.ordersEnabled)"START AUTOMATISCH" else "ACTIVEER LIVE")}
            OutlinedButton(onBacktest,Modifier.weight(1f),enabled=!busy){Text(if(busy)"TESTEN..." else "BACKTEST")}
        }
    }
    live?.let{val ratio=it.marginRatioPercent.coerceIn(0.0,100.0);val riskColor=when{ratio<25->mexcGreen;ratio<60->Color(0xFFFFC857);else->Color(0xFFFF5572)};Section("LIQUIDATIEMONITOR"){Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Text("MARGIN RATIO",color=Color.White,fontWeight=FontWeight.Bold);Text(pct(ratio),color=riskColor,fontSize=24.sp,fontWeight=FontWeight.Black)};LinearProgressIndicator(progress={ratio.toFloat()/100f},modifier=Modifier.fillMaxWidth().height(10.dp),color=riskColor,trackColor=Color(0xFF223044));Row(Modifier.fillMaxWidth().padding(top=9.dp),horizontalArrangement=Arrangement.SpaceBetween){Text("0% · veilig",color=mexcGreen,fontSize=10.sp);Text("100% · liquidatie",color=Color(0xFFFF5572),fontSize=10.sp)};Text("${if(it.isolated)"ISOLATED" else "CROSS"} · liquidatieprijs ${if(it.liquidationPrice>0)usd(it.liquidationPrice) else "wordt geladen"}",color=mexcMuted,fontSize=11.sp,modifier=Modifier.padding(top=8.dp))}}
    backtest?.let{Section("BACKTESTRESULTAAT"){Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween){Metric("SESSIES",it.sessions.toString());Metric("WIN",it.wins.toString());Metric("LOSS",it.losses.toString());Metric("MAX DD",pct(it.maxDrawdownPercent))};Text("${usd(it.startEquity)} → ${usd(it.endEquity)} · fees ${usd(it.totalFees)} · max DCA ${it.maxDca} · max exposure ${usd(it.maxExposure)}",color=Color.White,fontSize=12.sp,modifier=Modifier.padding(top=10.dp));Text("Piek margin ${pct(it.peakMarginUsagePercent)} · geschatte liquidatieafstand ${pct(it.estimatedLiquidationDistancePercent)}",color=if(it.estimatedLiquidationDistancePercent<s.minimumLiquidationDistance*100)Color(0xFFFF5572) else mexcGreen,fontSize=11.sp,modifier=Modifier.padding(top=6.dp));Text("Historische simulatie, geen winstgarantie.",color=mexcMuted,fontSize=10.sp)}}
}

@Composable private fun MexcSettingsPanel(s:MexcSettings,cloudConnected:Boolean,onChange:(MexcSettings)->Unit,onConnect:()->Unit){
    var advanced by remember{mutableStateOf(false)}
    Section("TEST 3 · BTC 200X HEDGE"){
        Text("LONG en SHORT draaien als twee afzonderlijke cycles en nemen ieder zelfstandig winst.",color=Color.White,fontSize=12.sp)
        SettingSwitch("Papertrading",s.mode==MexcMode.PAPER){onChange(s.copy(mode=if(it)MexcMode.PAPER else MexcMode.LIVE))}
        if(s.mode==MexcMode.LIVE)Text("REAL MONEY · de bot blijft uit tot jij START indrukt.",color=Color(0xFFFF6B81),fontWeight=FontWeight.Bold)
        NumberSetting("Paper startvermogen","USDT",s.paperEquity){onChange(s.copy(paperEquity=it))}
        Button(onConnect,Modifier.fillMaxWidth()){Text(if(cloudConnected)"MEXC-KOPPELING GECONTROLEERD" else "CONNECT MEXC CLOUD")}
    }
    Section("BASIC · JIJ VULT IN"){
        Text("BTC_USDT · CROSS · 200×",color=mexcGreen,fontWeight=FontWeight.Black)
        NumberSetting("Initial order size","USD NOTIONAL",s.initialOrderNotional){onChange(s.copy(initialOrderNotional=it))}
        PercentSetting("Take profit per kant",s.takeProfit){onChange(s.copy(takeProfit=it))}
        NumberSetting("Maximum DCA per kant","orders",s.maximumDcaOrders.toDouble()){onChange(s.copy(maximumDcaOrders=it.toInt().coerceIn(0,100)))}
        SettingSwitch("Emergency Hedge",s.emergencyHedgeEnabled){onChange(s.copy(emergencyHedgeEnabled=it))}
        NumberSetting("Emergency Equity Trigger","USDT EQUITY",s.emergencyEquityTrigger){onChange(s.copy(emergencyEquityTrigger=it))}
        SettingSwitch("Rescue Trading",s.rescueEnabled){onChange(s.copy(rescueEnabled=it))}
        NumberSetting("Rescue order size per kant","USD NOTIONAL",s.rescueOrderNotional){onChange(s.copy(rescueOrderNotional=it))}
        Text("${usd(s.initialOrderNotional)} notional gebruikt bij 200× theoretisch ongeveer ${usd(s.initialOrderNotional/200.0)} initiële margin per kant.",color=mexcMuted,fontSize=11.sp)
    }
    OutlinedButton(onClick={advanced=!advanced},modifier=Modifier.fillMaxWidth().padding(top=12.dp)){Text(if(advanced)"VERBERG ADVANCED" else "OPEN ADVANCED")}
    if(advanced) Section("ADVANCED · DCA & HEDGE"){
        TimeframeSetting("DCA timing/reference",s.executionTimeframe,MexcAdaptiveEngine.executionTimeframes){onChange(s.copy(executionTimeframe=it))}
        PercentSetting("DCA spacing per kant",s.dcaSpacing){onChange(s.copy(dcaSpacing=it))}
        PercentSetting("Emergency hedge ratio",s.emergencyHedgeRatio){onChange(s.copy(emergencyHedgeRatio=it))}
        PercentSetting("Rescue TP",s.rescueTakeProfit){onChange(s.copy(rescueTakeProfit=it))}
        NumberSetting("Minimum safetybuffer","USDT",s.minimumAvailableBuffer){onChange(s.copy(minimumAvailableBuffer=it))}
        NumberSetting("Maximum frozen cycles","cycle",s.maxFrozenCycles.toDouble()){onChange(s.copy(maxFrozenCycles=it.toInt().coerceIn(0,1)))}
        PercentSetting("Maximale MEXC margin ratio",s.maximumMarginRatio){onChange(s.copy(maximumMarginRatio=it))}
        PercentSetting("Minimale liquidatieafstand",s.minimumLiquidationDistance){onChange(s.copy(minimumLiquidationDistance=it))}
        Text("Classic stop-loss: UIT · de noodrem gebruikt EQUITY, niet wallet balance.",color=mexcGreen,fontWeight=FontWeight.Bold)
    }
    Text("Automatisch via MEXC: wallet balance, equity, available/used/maintenance margin, PNL, Long, Short en open orders.",color=mexcMuted,fontSize=11.sp,modifier=Modifier.padding(12.dp))
}

@Composable private fun MexcLegacySettingsPanel(s:MexcSettings,cloudConnected:Boolean,onChange:(MexcSettings)->Unit,onConnect:()->Unit){
    Section("JIJ VULT IN · HANDELSMODUS"){SettingSwitch("Papertrading (standaard)",s.mode==MexcMode.PAPER){onChange(s.copy(mode=if(it)MexcMode.PAPER else MexcMode.LIVE))};if(s.mode==MexcMode.LIVE)Text("REAL MONEY wordt pas vrijgegeven nadat de persoonlijke cloud API, hedge mode, saldo en safetycontroles opnieuw heeft gecontroleerd.",color=Color(0xFFFF6B81),fontSize=11.sp);NumberSetting("Paper startvermogen","USDT",s.paperEquity){onChange(s.copy(paperEquity=it))};Button(onConnect,Modifier.fillMaxWidth()){Text(if(cloudConnected)"MEXC-CLOUDKOPPELING VERNIEUWEN" else "CONNECT MEXC CLOUD")}}
    Section("POSITIE · VAST UITVOERINGSPROFIEL"){Text("CROSS · 200× · geldt voor Long, DCA en Short Hedge",color=mexcGreen,fontWeight=FontWeight.Bold);Text("De orderwaarde blijft de ingestelde notional. MEXC reserveert bij 200× ongeveer notional ÷ 200 als initiële marge; de gedeelde Futures-equity vormt de Cross-buffer.",color=mexcMuted,fontSize=11.sp,modifier=Modifier.padding(vertical=6.dp));PercentSetting("Eerste Long",s.initialLongRatio){onChange(s.copy(initialLongRatio=it,leverage=MexcAdaptiveEngine.FIXED_LEVERAGE))};PercentSetting("Max Long exposure",s.maxLongRatio){onChange(s.copy(maxLongRatio=it,leverage=MexcAdaptiveEngine.FIXED_LEVERAGE))};PercentSetting("Minimale equityreserve",s.minimumEquityReserve){onChange(s.copy(minimumEquityReserve=it,leverage=MexcAdaptiveEngine.FIXED_LEVERAGE))}}
    Section("JIJ VULT IN · TIMEFRAMES"){
        TimeframeSetting("Execution Timeframe",s.executionTimeframe,MexcAdaptiveEngine.executionTimeframes){onChange(s.copy(executionTimeframe=it))}
        TimeframeSetting("Hedge / Risk Timeframe",s.riskTimeframe,MexcAdaptiveEngine.riskTimeframes){onChange(s.copy(riskTimeframe=it))}
        Text("DCA based on: ${s.executionTimeframe}",color=Color.White,fontWeight=FontWeight.Bold,modifier=Modifier.padding(top=8.dp))
        Text("Hedge decisions based on: ${s.riskTimeframe}",color=Color.White,fontWeight=FontWeight.Bold)
        Text("EMA, RSI, ATR, lower lows en candlebevestiging gebruiken de gekozen candles; cooldown blijft echte verstreken tijd.",color=mexcMuted,fontSize=10.sp,modifier=Modifier.padding(top=6.dp))
    }
    Section("JIJ VULT IN · DCA"){s.dcaRatios.forEachIndexed{index,ratio->PercentSetting("DCA ${index+1} van session equity",ratio){value->val next=s.dcaRatios.toMutableList().also{it[index]=value};onChange(s.copy(dcaRatios=next))}};PercentSetting("Minimale prijsafstand",s.minimumSpacing){onChange(s.copy(minimumSpacing=it))};NumberSetting("ATR multiplier","x",s.atrMultiplier){onChange(s.copy(atrMultiplier=it))};NumberSetting("Cooldown","seconden",s.cooldownSeconds.toDouble()){onChange(s.copy(cooldownSeconds=it.toLong().coerceAtLeast(0)))}}
    Section("JIJ VULT IN · HEDGE & PROFIT"){SettingSwitch("Dynamic Short Hedge",s.hedgeEnabled){onChange(s.copy(hedgeEnabled=it))};PercentSetting("Drawdown hedge-trigger",s.hedgeDrawdownTrigger){onChange(s.copy(hedgeDrawdownTrigger=it))};NumberSetting("Risk score trigger","0-100",s.riskTrigger.toDouble()){onChange(s.copy(riskTrigger=it.toInt().coerceIn(0,100)))};PercentSetting("Initiële hedge",s.initialHedgeRatio){onChange(s.copy(initialHedgeRatio=it))};PercentSetting("Maximale hedge",s.maxHedgeRatio){onChange(s.copy(maxHedgeRatio=it))};NumberSetting("Recovery naar 37.5%","score",s.recoveryStep1.toDouble()){onChange(s.copy(recoveryStep1=it.toInt().coerceIn(0,100)))};NumberSetting("Recovery naar 25%","score",s.recoveryStep2.toDouble()){onChange(s.copy(recoveryStep2=it.toInt().coerceIn(0,100)))};NumberSetting("Recovery naar 12.5%","score",s.recoveryStep3.toDouble()){onChange(s.copy(recoveryStep3=it.toInt().coerceIn(0,100)))};NumberSetting("Recovery hedge uit","score",s.recoveryStep4.toDouble()){onChange(s.copy(recoveryStep4=it.toInt().coerceIn(0,100)))};PercentSetting("Take profit boven average entry",s.takeProfit){onChange(s.copy(takeProfit=it))};PercentSetting("Minimaal nettoresultaat",s.minimumNetProfit){onChange(s.copy(minimumNetProfit=it))}}
    Section("JIJ VULT IN · ABSOLUTE VEILIGHEID"){PercentSetting("Maximale sessiedrawdown",s.maximumSessionDrawdown){onChange(s.copy(maximumSessionDrawdown=it))};PercentSetting("Maximale marginbelasting",s.maximumMarginUsage){onChange(s.copy(maximumMarginUsage=it))};PercentSetting("Maximale MEXC margin ratio",s.maximumMarginRatio){onChange(s.copy(maximumMarginRatio=it))};PercentSetting("Minimale liquidatieafstand",s.minimumLiquidationDistance){onChange(s.copy(minimumLiquidationDistance=it))}}
    Text("Automatisch opgehaald: wallet equity, available balance, maintenance margin, contractminimum, toegestane leverage, BTC-prijs, fees, funding, posities en orders.",color=mexcMuted,fontSize=11.sp,modifier=Modifier.padding(12.dp))
}

@Composable private fun Section(title:String,content:@Composable ColumnScope.()->Unit)=Surface(color=Color(0xCC0B1521),shape=RoundedCornerShape(18.dp),modifier=Modifier.fillMaxWidth().padding(top=12.dp)){Column(Modifier.padding(14.dp)){Text(title,color=mexcBlue,fontSize=12.sp,fontWeight=FontWeight.Bold);Spacer(Modifier.height(10.dp));content()}}
@Composable private fun Metric(label:String,value:String)=Column(horizontalAlignment=Alignment.CenterHorizontally){Text(label,color=mexcMuted,fontSize=9.sp);Text(value,color=Color.White,fontSize=13.sp,fontWeight=FontWeight.Bold)}
@Composable private fun SettingSwitch(label:String,value:Boolean,onChange:(Boolean)->Unit)=Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){Text(label,color=Color.White,modifier=Modifier.weight(1f));Switch(value,onChange)}
@Composable private fun PercentSetting(label:String,value:Double,onChange:(Double)->Unit)=NumberSetting(label,"%",value*100){onChange(it/100)}
@Composable private fun TimeframeSetting(label:String,value:String,options:List<String>,onChange:(String)->Unit){
    var open by remember{mutableStateOf(false)}
    Box(Modifier.fillMaxWidth().padding(vertical=4.dp)){
        OutlinedButton(onClick={open=true},modifier=Modifier.fillMaxWidth()){Text("$label   [ $value ▼ ]")}
        DropdownMenu(expanded=open,onDismissRequest={open=false}){options.forEach{option->DropdownMenuItem(text={Text(option)},onClick={onChange(option);open=false})}}
    }
}
@Composable private fun NumberSetting(label:String,unit:String,value:Double,onChange:(Double)->Unit){var text by remember(value){mutableStateOf(String.format(Locale.US,"%.2f",value))};OutlinedTextField(text,{text=it.filter{c->c.isDigit()||c=='.'||c=='-'};text.toDoubleOrNull()?.let(onChange)},label={Text("JIJ VULT IN · $label")},suffix={Text(unit)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),singleLine=true,modifier=Modifier.fillMaxWidth().padding(vertical=4.dp))}
@Composable private fun MexcConnectDialog(onClose:()->Unit,onSave:(String,String)->Unit){var key by remember{mutableStateOf("")};var secret by remember{mutableStateOf("")};AlertDialog(onDismissRequest=onClose,title={Text("Connect MEXC")},text={Column{Text("Gebruik alleen een MEXC API-key met lezen en Futures trading. Nooit withdrawal-permission.");OutlinedTextField(key,{key=it.trim()},label={Text("API Key")});OutlinedTextField(secret,{secret=it.trim()},label={Text("Secret Key")},visualTransformation=PasswordVisualTransformation())}},confirmButton={Button(onClick={onSave(key,secret)},enabled=key.length>=8&&secret.length>=8){Text("VERSLEUTELD OPSLAAN")}},dismissButton={TextButton(onClick=onClose){Text("Annuleren")}})}
private fun usd(v:Double)=String.format(Locale.US,"$%,.2f",v);private fun pct(v:Double)=String.format(Locale.US,"%.2f%%",v)
