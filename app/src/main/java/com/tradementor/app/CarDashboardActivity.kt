package com.tradementor.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.fragment.app.FragmentActivity

class CarDashboardActivity : FragmentActivity() {
    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this)
        setContentView(webView)

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            cacheMode = WebSettings.LOAD_DEFAULT
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
            userAgentString = "$userAgentString AmarCarDashboard/1.0"
        }
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean = false
            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                applyCarLayout(view)
            }
        }
        webView.loadUrl("https://amar-bot-v44-direct-install-cyyaq5otyq-ez.a.run.app")
    }

    private fun applyCarLayout(view: WebView) {
        val js = """
            (function(){
              var old=document.getElementById('amar-car-dashboard-css');
              if(old) old.remove();
              var s=document.createElement('style');
              s.id='amar-car-dashboard-css';
              s.textContent=`
                html,body{background:#050806!important;overflow:auto!important}
                header,.bottom-nav,.mobile-nav,.app-nav,.bot-health-card,.direction-balance,
                .aster-recent-trades,.aster-action-gate,.dashboard-grid,footer{display:none!important}
                main{padding:10px 14px!important;max-width:none!important}
                .hero-panel{min-height:150px!important;margin:0 0 10px!important;padding:14px!important}
                .hero-panel .risk-orbit{transform:scale(.78)!important;transform-origin:center!important}
                .metric-strip{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:8px!important;margin:0!important}
                .metric-strip .metric{min-height:105px!important;padding:12px!important;border-radius:14px!important}
                .metric-strip .metric span{font-size:10px!important}
                .metric-strip .metric strong{font-size:23px!important;line-height:1.05!important}
                .metric-strip .metric small{font-size:9px!important}
                *{animation:none!important;transition:none!important}
              `;
              document.head.appendChild(s);
            })();
        """.trimIndent()
        view.evaluateJavascript(js, null)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }
}
