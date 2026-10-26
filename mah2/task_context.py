"""Only organizer-designated public task fields enter solver prompts."""
PUBLIC_FIELDS=('task_inst','output_fname','domain','domain_knowledge','dataset_preview','dataset_folder_tree')

def public_packet(row):
    return {k:row[k] for k in PUBLIC_FIELDS if k in row and row[k] is not None}

def input_packet(row,profile=None):
    """Apply the information boundary before any solver or optimizer sees a task."""
    if profile=='historical_task_only':
        return {k:row[k] for k in ('task_inst','output_fname')}
    if profile is not None:raise ValueError('Unknown task input profile: '+profile)
    return public_packet(row)

def render_task(packet):
    parts=[packet['task_inst']]
    for key,label in [('domain_knowledge','Public domain knowledge'),('dataset_folder_tree','Public dataset tree'),('dataset_preview','Public dataset preview')]:
        value=packet.get(key)
        if value and str(value).strip().lower() not in ('nan','none'):
            parts.append(label+':\n'+str(value))
    if packet.get('output_fname'):parts.append('Required output path: '+packet['output_fname'])
    return '\n\n'.join(parts)
