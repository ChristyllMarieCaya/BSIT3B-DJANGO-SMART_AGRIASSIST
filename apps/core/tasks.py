try:
    from celery import shared_task
    from apps.core.automation import run_all_agricultural_automations

    @shared_task
    def execute_agricultural_automations():
        result = run_all_agricultural_automations()
        return result.to_dict()
except ImportError:
    pass
