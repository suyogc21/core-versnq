package in.versnq.core;

import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.CapConfig;

/**
 * Versnq Core for Android (calls plan, step C4).
 *
 * First launch: the app's own start page (www/index.html) asks for the company address.
 * After that the app opens that company's Core directly: the same screens and logins as the web.
 * Only that one address gets the native bridge (Capacitor injects it into the server URL only),
 * and only it may be navigated to inside the app; every other link opens outside the app.
 * versnq-core://reset (the offline page, or Core's "Use a different company") forgets the company.
 */
public class MainActivity extends BridgeActivity {

    static final String PREFS = "versnq";
    static final String BASE_DOMAIN = "core.versnq.in";
    static final String USER_AGENT = "VersnqCoreApp/" + BuildConfig.VERSION_NAME;

    static String companyHost(String slug) {
        return slug + "." + BASE_DOMAIN;
    }

    static SharedPreferences prefs(android.content.Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        registerPlugin(ShellPlugin.class);
        String slug = prefs(this).getString("slug", null);
        if (slug != null && ShellPlugin.validSlug(slug)) {
            String host = companyHost(slug);
            config = new CapConfig.Builder(this)
                .setServerUrl("https://" + host)
                .setAllowNavigation(new String[] { host })
                .setErrorPath("error.html?core=" + Uri.encode("https://" + host))
                .setAppendedUserAgentString(USER_AGENT)
                .create();
        }
        super.onCreate(savedInstanceState);
    }
}
