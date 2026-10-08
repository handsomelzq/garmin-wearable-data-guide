"""Fail closed if a release contains unsupported files, records, or likely identifiers."""
import argparse,csv,json,re,subprocess
from pathlib import Path

ALLOWED_SUFFIXES={'.md','.py','.toml','.csv','.json'}
PATTERNS={
    'mobile_number':re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)'),
    'cohort_identifier':re.compile(r'\b[A-Z]{4}\d{4}\b'),
    'personal_email':re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'),
    'user_home_path':re.compile('/'+'Users'+'/'+r'[^/\s]+'),
    'github_token':re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    'private_document':re.compile(r'https?://(?:docs\.qq\.com/(?:sheet|doc)|[^/]*feishu\.cn/(?:wiki|docx))/\w+'),
}


def inspect_text(text):
    return [name for name,pattern in PATTERNS.items() if pattern.search(text)]


def allowed(path):
    if path=='.gitignore' or path=='README.md' or path=='pyproject.toml':return True
    parts=Path(path).parts
    if not parts or parts[0] not in {'src','docs','tests','schemas','examples'}:return False
    if any(part.startswith('.') or part in {'__pycache__','tokens','data','results','private_work'} for part in parts):return False
    if Path(path).suffix not in ALLOWED_SUFFIXES:return False
    if Path(path).suffix=='.csv':return parts[0]=='examples' and path.endswith('_headers.csv')
    if Path(path).suffix=='.json':return parts[0]=='schemas' or path=='examples/accounts.example.json'
    return True


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--staged',action='store_true');args=parser.parse_args();root=args.root.resolve()
    if args.staged:
        output=subprocess.check_output(['git','-C',str(root),'diff','--cached','--name-only','--diff-filter=ACMR','-z'])
        paths=[p.decode() for p in output.split(b'\0') if p]
    else:
        paths=[str(p.relative_to(root)) for p in root.rglob('*') if (p.is_file() or p.is_symlink()) and '.git' not in p.parts and '__pycache__' not in p.parts]
    violations=[]
    for relative in sorted(paths):
        path=root/relative
        if path.is_symlink() or not allowed(relative):
            violations.append({'path':relative,'reason':'not_in_release_allowlist'});continue
        try:
            if args.staged:
                mode=subprocess.check_output(['git','-C',str(root),'ls-files','--stage','--',relative],text=True).split()[0]
                if mode=='120000':
                    violations.append({'path':relative,'reason':'symlink_in_index'});continue
                text=subprocess.check_output(['git','-C',str(root),'show',':'+relative]).decode('utf-8-sig')
            else:text=path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            violations.append({'path':relative,'reason':'non_text_file'});continue
        for match in inspect_text(relative+'\n'+text):violations.append({'path':relative,'reason':match})
        if path.suffix=='.csv':
            rows=list(csv.reader(text.splitlines()))
            if len(rows)!=1:violations.append({'path':relative,'reason':'example_csv_contains_records'})
    report={'checked_files':len(paths),'violations':violations,'passed':not violations}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if violations:raise SystemExit(1)


if __name__=='__main__':main()
