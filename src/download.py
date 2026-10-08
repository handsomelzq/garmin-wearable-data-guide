"""Download to an explicitly specified private directory; credentials use env vars."""
import argparse
import csv
import getpass
import hashlib
import io
import json
import logging
import os
import re
import time
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def validate_subject_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value or ''):
        raise ValueError('subject_id must contain only letters, digits, hyphens or underscores')
    return value


def excluded_for_missing(valid, expected, threshold):
    return valid / expected <= 1 - threshold + 1e-12


def screen_day(obj, day, sampling_seconds):
    """Count fixed local-day slots, including slots omitted from the server response."""
    start = int(datetime.fromisoformat(day + 'T00:00:00+08:00').timestamp() * 1000)
    valid = []
    timestamps = set()
    for row in obj.get('heartRateValues') or []:
        if not isinstance(row, list) or len(row) < 2 or not isinstance(row[0], (int, float)):
            continue
        if not start <= row[0] < start + 86400000:
            continue
        timestamps.add(row[0])
        if isinstance(row[1], (int, float)) and 30 <= row[1] < 255:
            valid.append(row[0])
    timestamps = sorted(timestamps)
    gaps = [round((b - a) / 1000) for a, b in zip(timestamps, timestamps[1:]) if 0 < b - a <= 600000]
    cadence = Counter(gaps).most_common(1)[0][0] if gaps else None
    slots = len({int((t - start) // (sampling_seconds * 1000)) for t in valid})
    expected = 86400 // sampling_seconds
    return {
        'local_date': day, 'request_success': True,
        'expected_slots': expected, 'valid_slots': slots,
        'valid_reading_minutes': len({int((t - start) // 60000) for t in valid}),
        'heart_rate_missing_rate': 1 - slots / expected,
        'modal_sampling_seconds': cadence,
    }


def unpack(blob, output):
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        count = 0
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = Path(item.filename).name
            if name:
                (output / name).write_bytes(archive.read(item))
                count += 1
        return count


class Collector:
    def __init__(self, root, pause):
        self.root = root
        self.pause = pause

    def log(self, sid, kind, day, status, detail=''):
        path = self.root / 'logs/download_status.csv'
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not path.exists()
        with path.open('a', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            if fresh:
                writer.writerow(['subject_id', 'dataset', 'date_or_id', 'status', 'detail'])
            writer.writerow([sid, kind, day, status, detail])
        print(sid, kind, day, status, flush=True)

    def fetch(self, sid, kind, day, call, output=None):
        if output and output.exists():
            return json.loads(output.read_text(encoding='utf-8'))
        for attempt in range(3):
            try:
                obj = call()
                if output:
                    save(output, obj)
                self.log(sid, kind, day, 'downloaded' if obj else 'empty')
                time.sleep(self.pause)
                return obj
            except Exception as error:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    self.log(sid, kind, day, 'error', type(error).__name__)
        return None

    def subject(self, account, days, boundary_day, args):
        from garminconnect import Garmin
        sid = validate_subject_id(account['subject_id'])
        root = self.root / 'data' / sid
        result = {'subject_id': sid, 'period_start': days[0], 'period_end_exclusive': boundary_day,
                  'expected_minutes': len(days) * 1440}
        def mfa():
            if args.interactive_mfa:
                return getpass.getpass('Garmin verification code: ')
            raise RuntimeError('interactive MFA required')
        try:
            login = os.environ[account['account_env']]
            password = os.environ[account['password_env']]
            token = self.root / '.tokens' / sid
            token.mkdir(parents=True, exist_ok=True)
            os.chmod(token, 0o700)
            client = Garmin(email=login, password=password, is_cn=bool(account.get('is_cn', True)), prompt_mfa=mfa)
            client.login(tokenstore=str(token))
            del login, password
        except Exception as error:
            result.update(status='login_failed', error_type=type(error).__name__)
            save(self.root / 'screening' / f'{sid}_summary.json', result)
            return
        daily = []
        for day in days:
            obj = self.fetch(sid, 'heart_rate_screen', day, lambda: client.get_heart_rates(day),
                             root / 'connect_extra/heart_rate' / f'{day}.json')
            row = screen_day(obj, day, args.sampling_seconds) if isinstance(obj, dict) else {
                'local_date': day, 'request_success': False, 'expected_slots': 86400 // args.sampling_seconds}
            row['subject_id'] = sid
            daily.append(row)
        save(self.root / 'screening' / f'{sid}_daily.json', daily)
        successes = sum(row['request_success'] for row in daily)
        result['successful_screen_days'] = successes
        cadences = {row.get('modal_sampling_seconds') for row in daily} - {None}
        if successes != len(days):
            result['status'] = 'screen_failed'
        elif cadences - {args.sampling_seconds}:
            result['status'] = 'screen_cadence_review'
        else:
            valid = sum(row['valid_slots'] for row in daily)
            expected = len(days) * (86400 // args.sampling_seconds)
            rate = 1 - valid / expected
            result.update(expected_slots=expected, valid_slots=valid, heart_rate_missing_rate=rate,
                          estimated_covered_minutes=valid * args.sampling_seconds / 60,
                          valid_reading_minutes=sum(row['valid_reading_minutes'] for row in daily),
                          status='excluded_hr_missing' if excluded_for_missing(valid, expected, args.missing_threshold) else 'included')
        save(self.root / 'screening' / f'{sid}_summary.json', result)
        if result['status'] != 'included':
            return
        for day in days + [boundary_day]:
            marker = root / 'audit' / f'wellness_{day}.done'
            if not marker.exists():
                blob = self.fetch(sid, 'wellness_fit', day, lambda: client.download_health_snapshot(day))
                if blob is not None:
                    try:
                        count = unpack(blob, root / 'raw/wellness')
                        marker.parent.mkdir(parents=True, exist_ok=True)
                        marker.write_text(str(count))
                    except Exception as error:
                        self.log(sid, 'wellness_unpack', day, 'error', type(error).__name__)
            self.fetch(sid, 'sleep', day, lambda: client.get_sleep_data(day), root / 'sleep/json' / f'{day}.json')
            if day in days:
                self.fetch(sid, 'official', day, lambda: client.get_user_summary(day), root / 'official/json' / f'{day}.json')
        acts = self.fetch(sid, 'activities_list', 'period',
                          lambda: client.get_activities_by_date(days[0], days[-1]), root / 'raw/activities/activities.json')
        for activity in acts or []:
            aid = activity['activityId']
            target = root / 'raw/activities' / str(aid)
            if not list(target.glob('*')):
                blob = self.fetch(sid, 'activity_fit', str(aid),
                                  lambda: client.download_activity(aid, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL))
                if blob:
                    try:
                        unpack(blob, target)
                    except Exception as error:
                        self.log(sid, 'activity_unpack', str(aid), 'error', type(error).__name__)
        methods = {'stress': 'get_all_day_stress', 'body_battery': 'get_body_battery',
                   'spo2': 'get_spo2_data', 'respiration': 'get_respiration_data', 'hrv': 'get_hrv_data',
                   'steps': 'get_steps_data', 'floors': 'get_floors', 'intensity_minutes': 'get_intensity_minutes_data'}
        for kind, method in methods.items():
            for day in days:
                self.fetch(sid, kind, day, lambda: getattr(client, method)(day),
                           root / 'connect_extra' / kind / f'{day}.json')
        result['download_phase'] = 'finished'
        save(self.root / 'screening' / f'{sid}_summary.json', result)


def main():
    parser = argparse.ArgumentParser(description='Download authorized Garmin data into a private local directory')
    parser.add_argument('--accounts', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--start', required=True, type=date.fromisoformat)
    parser.add_argument('--end', required=True, type=date.fromisoformat, help='Exclusive local midnight')
    parser.add_argument('--missing-threshold', type=float, default=.8)
    parser.add_argument('--sampling-seconds', type=int, default=120)
    parser.add_argument('--pause', type=float, default=.4)
    parser.add_argument('--interactive-mfa', action='store_true')
    args = parser.parse_args()
    if args.end <= args.start or not 0 <= args.missing_threshold <= 1:
        parser.error('Invalid date range or missing threshold')
    if args.sampling_seconds <= 0 or 86400 % args.sampling_seconds:
        parser.error('sampling-seconds must divide one day exactly')
    accounts = json.loads(args.accounts.read_text(encoding='utf-8'))
    accounts = [a for a in accounts if str(a.get('wears_band', True)).lower() in ('true', 'yes', '1')]
    sids = [validate_subject_id(a['subject_id']) for a in accounts]
    if len(sids) != len(set(sids)):
        parser.error('Duplicate subject identifiers')
    for a in accounts:
        for key in ['account_env', 'password_env']:
            if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', a[key]):
                parser.error('Credential entries must name environment variables')
    args.root = args.root.resolve()
    public_root = Path(__file__).resolve().parent.parent
    if args.root == public_root or public_root in args.root.parents:
        parser.error('Private working directory must be outside the public code directory')
    config = {'start': args.start.isoformat(), 'end_exclusive': args.end.isoformat(),
              'timezone': 'Asia/Shanghai', 'missing_threshold': args.missing_threshold,
              'sampling_seconds': args.sampling_seconds, 'subjects': sorted(sids),
              'account_fingerprints': {a['subject_id']: hashlib.sha256(os.environ.get(a['account_env'], '').encode()).hexdigest()
                                       for a in accounts}}
    config_path = args.root / 'run_config.json'
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        parser.error('Existing batch has different accounts, dates or screening rules; use a new private directory')
    args.root.mkdir(parents=True, exist_ok=True)
    os.chmod(args.root, 0o700)
    days = [(args.start + timedelta(days=i)).isoformat() for i in range((args.end - args.start).days)]
    save(config_path, config)
    logging.getLogger('garth').setLevel(logging.CRITICAL)
    collector = Collector(args.root, args.pause)
    for account in accounts:
        collector.subject(account, days, args.end.isoformat(), args)


if __name__ == '__main__':
    main()
