"""Offline processing; preserves raw downloads and emits three analytical CSVs."""
import argparse,json,subprocess,sys
from pathlib import Path
from datetime import date,timedelta
import pandas as pd
import sleep_download
from download import validate_subject_id
SOURCE=Path(__file__).resolve().parent
HEAD=json.loads((SOURCE.parent/'schemas/data_headers.json').read_text())
def run(root,name,*args):
    root.joinpath('audit').mkdir(parents=True,exist_ok=True)
    with (root/'audit'/f'{name}.log').open('w') as f:
        r=subprocess.run([sys.executable,str(SOURCE/f'{name}.py'),*map(str,args)],stdout=f,stderr=subprocess.STDOUT)
    return r.returncode==0

def read(p):
    try:return pd.read_csv(p,low_memory=False)
    except (FileNotFoundError,pd.errors.EmptyDataError):return pd.DataFrame()

def timed(root,name):
    d=read(root/'csv'/name)
    if d.empty or 'local_time' not in d:return pd.DataFrame()
    d['time']=pd.to_datetime(d.local_time,format='mixed',utc=True,errors='coerce').dt.tz_convert('Asia/Shanghai')
    d=d[(d.time>=START)&(d.time<STOP)].copy();d['minute']=d.time.dt.floor('min')
    return d

def panel(root,sid):
    p=pd.DataFrame(index=pd.date_range(START,STOP,inclusive='left',freq='min'));p.index.name='minute'
    m=timed(root,'monitoring.csv');st=timed(root,'stress_level.csv');sp=timed(root,'spo2_data.csv')
    sources=[]
    if not m.empty and 'heart_rate' in m:
        m.heart_rate=pd.to_numeric(m.heart_rate,errors='coerce')
        h=m[m.heart_rate.between(30,254)].drop_duplicates(['time','heart_rate'])
        p=p.join(h.groupby('minute').heart_rate.agg(heart_rate_mean_bpm='mean',heart_rate_observation_count='size'))
        sources.append(h[['minute','source_file']])
    if not st.empty and 'stress_level_value' in st:
        st=st.drop_duplicates([c for c in st if c!='source_file'])
        v=pd.to_numeric(st.stress_level_value,errors='coerce');st['valid']=v.where(v.between(0,100))
        p=p.join(st.groupby('minute').agg(stress_score=('valid','mean'),stress_valid_observation_count=('valid','count'),stress_raw_observation_count=('stress_level_value','size')))
        for src,target in [('2','manufacturer_field_2'),('3','body_battery_score_estimate'),('4','manufacturer_status_code'),('stress_level_time','stress_record_time_utc')]:
            if src in st:
                g=st.sort_values('time').groupby('minute')[src]
                p[target]=g.mean() if src=='3' else g.first() if src=='stress_level_time' else g.last()
        sources.append(st[['minute','source_file']])
    if not sp.empty and 'reading_spo2' in sp:
        sp['reading_spo2']=pd.to_numeric(sp.reading_spo2,errors='coerce')
        sp=sp[sp.reading_spo2.gt(0)&sp.reading_spo2.le(100)].drop_duplicates([c for c in sp if c!='source_file'])
        g=sp.sort_values('time').groupby('minute')
        p['spo2_percent']=g.reading_spo2.mean()
        p['spo2_reading_time_local']=g.time.first().map(lambda t:t.isoformat())
        p['spo2_reading_time_utc']=g.time.first().map(lambda t:t.tz_convert('UTC').isoformat())
        if 'reading_confidence' in sp:p['spo2_confidence_score']=g.reading_confidence.mean()
        if 'mode' in sp:p['spo2_measurement_mode']=g['mode'].agg(lambda v:';'.join(sorted(set(map(str,v.dropna())))))
        sources.append(sp[['minute','source_file']])
    if sources:p['source_file']=pd.concat(sources).groupby('minute').source_file.agg(lambda v:';'.join(sorted(set(v.dropna()))))
    p['subject_id']=sid;p['minute_start_local']=[x.isoformat() for x in p.index];p['local_date']=p.index.strftime('%Y-%m-%d')
    for h in HEAD['minute_data']:
        if h not in p:p[h]=None
    for h in ['heart_rate_observation_count','stress_valid_observation_count','stress_raw_observation_count']:p[h]=p[h].fillna(0).astype(int)
    return p[HEAD['minute_data']]

def daily(root,sid):
    ds=read(root/'analysis/daily_fit.csv');steps=read(root/'analysis/daily_steps.csv')
    ds={str(r['local_date']):r for r in ds.to_dict('records')};steps={str(r['local_date']):r for r in steps.to_dict('records')}
    sleep={}
    if list((root/'sleep/json').glob('*.json')):
        if hasattr(sleep_download.fit_unmeasurable_pct,'cache'):del sleep_download.fit_unmeasurable_pct.cache
        nights,_,_=sleep_download.build(sid,root/'sleep',root/'csv/sleep_level.csv','Asia/Shanghai')
        sleep={r['wake_date']:r for r in nights.to_dict('records')}
    fitmap={'heart_rate_observation_count':'hr_n','heart_rate_mean_bpm':'hr_mean','heart_rate_min_bpm':'hr_min','heart_rate_max_bpm':'hr_max','fit_cycles':'cycles','stress_valid_observation_count':'stress_n','stress_mean_score':'stress_mean','stress_max_score':'stress_max','stress_observation_count':'stress_total','stress_valid_percent':'stress_valid_pct'}
    offmap={'distance_m':'totalDistanceMeters','active_calories_kcal':'activeKilocalories','resting_heart_rate_bpm':'restingHeartRate','moderate_intensity_minutes':'moderateIntensityMinutes','vigorous_intensity_minutes':'vigorousIntensityMinutes','floors_ascended_m':'floorsAscendedInMeters','floors_descended_m':'floorsDescendedInMeters','body_battery_highest':'bodyBatteryHighestValue','body_battery_lowest':'bodyBatteryLowestValue','body_battery_charged':'bodyBatteryChargedValue','body_battery_drained':'bodyBatteryDrainedValue','body_battery_at_wake':'bodyBatteryAtWakeTime','official_total_steps':'totalSteps'}
    slmap={'sleep_record_valid':'valid','sleep_duration_minutes':'sleep_min','sleep_start_local':'sleep_start','sleep_end_local':'sleep_end','deep_sleep_minutes':'deep_min','light_sleep_minutes':'light_min','rem_sleep_minutes':'rem_min','awake_minutes':'awake_min','unmeasurable_sleep_minutes':'unmeasurable_min','nap_minutes':'nap_min','sleep_heart_rate_mean_bpm':'sleep_hr_mean','sleep_resting_heart_rate_bpm':'resting_hr','sleep_stress_mean_score':'sleep_stress_mean','sleep_body_battery_change':'body_battery_change'}
    rows=[]
    for d in DAYS:
        row={'subject_id':sid,'local_date':d};ft=ds.get(d,{});sl=sleep.get(d,{});ts=steps.get(d,{})
        q=root/'official/json'/f'{d}.json';off=json.loads(q.read_text()) if q.exists() else {}
        row.update({k:ft.get(v) for k,v in fitmap.items()});row.update({k:off.get(v) for k,v in offmap.items()});row.update({k:sl.get(v) for k,v in slmap.items()})
        row['active_time_s']=sum(off[v] for v in ['activeSeconds','highlyActiveSeconds']) if all(off.get(v) is not None for v in ['activeSeconds','highlyActiveSeconds']) else None
        row['weighted_intensity_minutes']=row['moderate_intensity_minutes']+2*row['vigorous_intensity_minutes'] if row['moderate_intensity_minutes'] is not None and row['vigorous_intensity_minutes'] is not None else None
        row['running_steps']=ts.get('steps_running');row['walking_steps']=ts.get('steps_walking');rows.append(row)
    return pd.DataFrame(rows).reindex(columns=HEAD['daily_data'])

def activities(root,sid):
    p=root/'raw/activities/activities.json';rows=[]
    fields={'activity_id':'activityId','activity_start_local':'startTimeLocal','is_favorite':'isFavorite','activity_name':'activityName','calories_kcal':'calories','duration_s':'duration','average_heart_rate_bpm':'averageHR','maximum_heart_rate_bpm':'maxHR','average_cadence_spm':'averageRunningCadenceInStepsPerMinute','maximum_cadence_spm':'maxRunningCadenceInStepsPerMinute','activity_steps':'steps','best_lap_duration_s':'minActivityLapDuration','lap_count':'lapCount','moving_duration_s':'movingDuration','elapsed_duration_s':'elapsedDuration','training_stress_score':'trainingStressScore','stress_relief_activity':'stressReliefActivity'}
    for a in json.loads(p.read_text()) if p.exists() else []:
        t=pd.Timestamp(a.get('startTimeLocal'));t=t.tz_localize('Asia/Shanghai') if t.tzinfo is None else t.tz_convert('Asia/Shanghai')
        if not START<=t<STOP:continue
        row={'subject_id':sid,**{k:a.get(v) for k,v in fields.items()},'activity_type':(a.get('activityType') or {}).get('typeKey')}
        row['distance_km']=a['distance']/1000 if a.get('distance') is not None else None
        row['average_stride_length_m']=a['avgStrideLength']/100 if a.get('avgStrideLength') is not None else None
        for src,target in [('averageSpeed','average_pace_min_per_km'),('maxSpeed','best_pace_min_per_km')]:row[target]=1000/(a[src]*60) if a.get(src,0) and a[src]>0 else None
        rows.append(row)
    return pd.DataFrame(rows,columns=HEAD['activities']).drop_duplicates(['subject_id','activity_id'])
def main():
    global BASE,DAYS,START,STOP
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args();BASE=args.root.resolve()
    config=json.loads((BASE/'run_config.json').read_text())
    start=date.fromisoformat(config['start']);end=date.fromisoformat(config['end_exclusive'])
    DAYS=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days)]
    START=pd.Timestamp(start,tz='Asia/Shanghai');STOP=pd.Timestamp(end,tz='Asia/Shanghai')
    frames={k:[] for k in HEAD};summaries=[];daily_quality=[];screen_rows=[];errors=[]
    for file in sorted((BASE/'screening').glob('*_summary.json')):
        summary=json.loads(file.read_text());summaries.append(summary)
        sid=validate_subject_id(summary['subject_id']);root=BASE/'data'/sid
        day_file=BASE/'screening'/f'{sid}_daily.json'
        if day_file.exists():screen_rows.extend(json.loads(day_file.read_text()))
        if summary['status']!='included':continue
        if summary.get('download_phase')!='finished':
            errors.append({'subject_id':sid,'stage':'download','status':'not_finished'});continue
        (root/'analysis').mkdir(parents=True,exist_ok=True)
        if list((root/'raw').rglob('*.fit')):
            for tool,parameters in [('fit2csv',[root/'raw','-o',root/'csv','--subject',sid,'--jobs',str(args.jobs)]),
                                    ('daily_summary',[root/'csv','-o',root/'analysis/daily_fit.csv']),
                                    ('steps_recount',[root/'csv','-o',root/'analysis/daily_steps.csv'])]:
                if not run(root,tool,*parameters):errors.append({'subject_id':sid,'stage':tool,'status':'failed'})
        try:
            p=panel(root,sid);d=daily(root,sid);a=activities(root,sid)
            assert len(p)==len(DAYS)*1440 and len(d)==len(DAYS)
            for name,df in [('daily_data',d),('minute_data',p),('activities',a)]:
                df.to_csv(root/'analysis'/f'{name}.csv',index=False,encoding='utf-8-sig');frames[name].append(df)
            summary.update(fit_hr_valid_minutes=int(p.heart_rate_mean_bpm.notna().sum()),
                           stress_valid_minutes=int(p.stress_score.notna().sum()),
                           spo2_valid_minutes=int(p.spo2_percent.notna().sum()),
                           sleep_valid_days=int(d.sleep_record_valid.fillna(False).sum()),
                           official_steps_available_days=int(d.official_total_steps.notna().sum()),
                           activity_count=len(a),fit_file_count=len(list((root/'raw').rglob('*.fit'))))
            for day,group in p.groupby('local_date'):
                row=d[d.local_date==day].iloc[0]
                daily_quality.append({'subject_id':sid,'local_date':day,'expected_minutes':1440,
                                      'fit_hr_valid_minutes':int(group.heart_rate_mean_bpm.notna().sum()),
                                      'fit_hr_minute_missing_rate':1-group.heart_rate_mean_bpm.notna().sum()/1440,
                                      'stress_valid_minutes':int(group.stress_score.notna().sum()),
                                      'stress_minute_missing_rate':1-group.stress_score.notna().sum()/1440,
                                      'spo2_valid_minutes':int(group.spo2_percent.notna().sum()),
                                      'spo2_minute_missing_rate':1-group.spo2_percent.notna().sum()/1440,
                                      'sleep_record_valid':row.sleep_record_valid,
                                      'official_steps_available':pd.notna(row.official_total_steps)})
        except Exception as error:
            errors.append({'subject_id':sid,'stage':'aggregate','status':type(error).__name__})
    output=BASE/'results';output.mkdir(parents=True,exist_ok=True)
    for name,parts in frames.items():
        df=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=HEAD[name])
        keys={'daily_data':['subject_id','local_date'],'minute_data':['subject_id','minute_start_local'],
              'activities':['subject_id','activity_start_local']}[name]
        if len(df):df=df.sort_values(keys,kind='stable')
        assert not df.duplicated(['subject_id','activity_id'] if name=='activities' else keys).any()
        df.to_csv(output/f'{name}.csv',index=False,encoding='utf-8-sig')
    for name,rows in [('subject_missingness',summaries),('heart_rate_screen_by_day',screen_rows),
                      ('data_missingness_by_day',daily_quality),('processing_issues',errors)]:
        pd.DataFrame(rows).to_csv(output/f'{name}.csv',index=False,encoding='utf-8-sig')
    print('CSV export completed; processing issues:',len(errors))
    if errors:raise SystemExit(2)

if __name__=='__main__':main()
