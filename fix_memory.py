import re
with open(r'c:\hackathon\flipkart\TrafficFlow\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_cleanup = '''            if 'first_frame' in locals():
                del first_frame
            if 'mock_process_result' in locals():
                del mock_process_result
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except:
                pass'''

content = re.sub(r"if 'first_frame' in locals\(\):.*?gc\.collect\(\)", new_cleanup, content, flags=re.DOTALL)

with open(r'c:\hackathon\flipkart\TrafficFlow\app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Memory cleanup logic injected.')
