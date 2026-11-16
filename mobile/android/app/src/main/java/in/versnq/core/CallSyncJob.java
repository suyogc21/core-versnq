package in.versnq.core;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.provider.CallLog;

/**
 * Runs CallSync in the background, with Android's own job scheduler (no extra library):
 * - right after the call log changes (a call just ended), via a content trigger;
 * - every 15 minutes as a safety net (Android's shortest period), kept across restarts.
 * Both wait for an internet connection.
 */
public class CallSyncJob extends JobService {

    static final int ON_CALL_LOG_CHANGE = 1;
    static final int EVERY_15_MINUTES = 2;

    static void schedule(Context context) {
        JobScheduler js = context.getSystemService(JobScheduler.class);
        if (js == null) return;
        ComponentName me = new ComponentName(context, CallSyncJob.class);
        js.schedule(
            new JobInfo.Builder(ON_CALL_LOG_CHANGE, me)
                .addTriggerContentUri(
                    new JobInfo.TriggerContentUri(CallLog.Calls.CONTENT_URI, JobInfo.TriggerContentUri.FLAG_NOTIFY_FOR_DESCENDANTS)
                )
                .setTriggerContentUpdateDelay(3000)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .build()
        );
        if (js.getPendingJob(EVERY_15_MINUTES) == null) {
            js.schedule(
                new JobInfo.Builder(EVERY_15_MINUTES, me)
                    .setPeriodic(15 * 60 * 1000L)
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPersisted(true)
                    .build()
            );
        }
    }

    static void cancel(Context context) {
        JobScheduler js = context.getSystemService(JobScheduler.class);
        if (js != null) {
            js.cancel(ON_CALL_LOG_CHANGE);
            js.cancel(EVERY_15_MINUTES);
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        final Context context = getApplicationContext();
        new Thread(() -> {
            CallSync.run(context);
            jobFinished(params, false);
            if (MainActivity.prefs(context).getString(CallSync.KEY_TOKEN, null) != null) {
                schedule(context); // a content trigger fires once: arm it again
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true; // stopped early: run again later
    }
}
