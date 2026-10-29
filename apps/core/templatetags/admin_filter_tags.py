from django import template

register = template.Library()


@register.simple_tag
def admin_filter_choices(changelist, filter_spec):
    return list(filter_spec.choices(changelist))
