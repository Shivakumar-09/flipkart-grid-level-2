import re
import os

with open(r'c:\hackathon\flipkart\TrafficFlow\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Relocate /health to the top, before engines
health_endpoint = '''
@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok"
    })
'''

# Remove old health endpoint (handle potential line breaks)
content = re.sub(r'# Platform health checks.*?def health\(\):.*?return jsonify\(\{.*?"TrafficFlow"\s*\}\)', '', content, flags=re.DOTALL)
# Or manually just strip out the specific text
content = content.replace('''# Platform health checks should not trigger database, OCR, or YOLO work.
@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "service": "TrafficFlow"
    })''', '')

# Insert health right after Compress(app)
content = content.replace('Compress(app)', 'Compress(app)\n' + health_endpoint)

# 2. Make engines lazy-loaded proxy singletons
old_engine_block = '''# Import system engines
# (Delay engine import or wrap to handle potential runtime load anomalies cleanly)
try:
    from engine.violation_engine import ViolationEngine
    from engine.evidence_engine import EvidenceEngine
    from engine.analytics_engine import AnalyticsEngine

    violation_engine = ViolationEngine()
    evidence_engine = EvidenceEngine(
        db_path=os.path.join(DATABASE_DIR, "trafficflow.db"),
        output_dir=OUTPUTS_DIR
    )
    analytics_engine = AnalyticsEngine(
        db_path=os.path.join(DATABASE_DIR, "trafficflow.db")
    )
    logger.info("Engines integrated successfully.")
except Exception as e:
    logger.critical(f"Engine initialization failed: {e}")
    # Fallback placeholders if imports fail on fresh environment check
    violation_engine = None
    evidence_engine = None
    analytics_engine = None'''

new_engine_block = '''
# Lazy load engines
class LazyEngineProxy:
    def __init__(self, engine_name):
        self.engine_name = engine_name
        self._instance = None
    
    def _get_instance(self):
        if self._instance is None:
            if self.engine_name == 'violation':
                from engine.violation_engine import ViolationEngine
                self._instance = ViolationEngine()
            elif self.engine_name == 'evidence':
                from engine.evidence_engine import EvidenceEngine
                self._instance = EvidenceEngine(
                    db_path=os.path.join(DATABASE_DIR, "trafficflow.db"),
                    output_dir=OUTPUTS_DIR
                )
            elif self.engine_name == 'analytics':
                from engine.analytics_engine import AnalyticsEngine
                self._instance = AnalyticsEngine(
                    db_path=os.path.join(DATABASE_DIR, "trafficflow.db")
                )
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get_instance(), name)

violation_engine = LazyEngineProxy('violation')
evidence_engine = LazyEngineProxy('evidence')
analytics_engine = LazyEngineProxy('analytics')
'''

content = content.replace(old_engine_block, new_engine_block)

with open(r'c:\hackathon\flipkart\TrafficFlow\app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('app.py modified successfully.')
