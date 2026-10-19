"""Explicit live check; one workflow spends up to two SerpApi searches. Not a test fixture."""
import argparse
import json
import time
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid-searches', action='store_true', required=True)
    parser.add_argument('--product', default='Milton stainless steel water bottle 1 litre')
    parser.add_argument('--selling-price', default='799.00')
    args = parser.parse_args()
    started = time.perf_counter()
    with httpx.Client(timeout=25) as client:
        response = client.post('http://127.0.0.1:4111/orchestration/runs', json={
            'product_name': args.product, 'selling_price': args.selling_price, 'max_results': 3,
            'seller_attributes': {'category': 'bottle', 'capacity_ml': '1000', 'material': 'stainless steel', 'brand': 'Milton'},
        })
        response.raise_for_status()
        run_id = response.json()['run_id']
        deadline = time.monotonic() + 620
        while time.monotonic() < deadline:
            response = client.get(f'http://127.0.0.1:4111/orchestration/runs/{run_id}')
            response.raise_for_status()
            run = response.json()
            if run['status'] != 'running':
                report = run.get('result', {}).get('report', {})
                persistence = report.get('persistence', {})
                reopened = None
                if persistence.get('status') == 'saved':
                    saved = client.get(f"http://127.0.0.1:8000/api/reports/{persistence['report_id']}")
                    reopened = saved.status_code == 200 and saved.json()['intelligence']['report'] == report['report']
                print(json.dumps({
                    'status': run['status'], 'run_id': run_id, 'wall_ms': round((time.perf_counter() - started) * 1000),
                    'workflow_ms': run['duration_ms'], 'upstream_calls': run.get('upstream_calls'), 'steps': run['steps'],
                    'error': run.get('error'), 'persistence': persistence, 'reopened_matching_report': reopened,
                    'listing_count': len(report.get('listings', [])), 'benchmark_status': report.get('pricing', {}).get('benchmark_status'),
                    'performance': report.get('performance'),
                }, indent=2))
                return 0 if run['status'] == 'success' else 1
            time.sleep(1)
    print('Live run timed out. Check history before retrying.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
