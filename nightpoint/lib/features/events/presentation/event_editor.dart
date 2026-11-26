import 'package:flutter/material.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/idempotency_key.dart';
import '../data/event_repository.dart';

class EventEditor extends StatefulWidget {
  const EventEditor({super.key, required this.repository, this.previous});
  final EventRepository repository;
  final EventRecord? previous;

  @override
  State<EventEditor> createState() => _EventEditorState();
}

class _EventEditorState extends State<EventEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _title,
      _description,
      _place,
      _longitude,
      _latitude;
  late DateTime _starts;
  late String _category, _visibility;
  String _key = newIdempotencyKey();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final previous = widget.previous;
    _title = TextEditingController(text: previous?.title ?? '');
    _description = TextEditingController(text: previous?.description ?? '');
    _place = TextEditingController(
      text: previous?.locationLabel ?? 'Ponto sintético',
    );
    _longitude = TextEditingController(text: '${previous?.longitude ?? 0.0}');
    _latitude = TextEditingController(text: '${previous?.latitude ?? 0.0}');
    _starts =
        previous?.startsAt.toLocal() ??
        DateTime.now().add(const Duration(days: 1));
    _category = previous?.category ?? 'street';
    _visibility = previous?.visibility ?? 'listed';
  }

  @override
  void dispose() {
    for (final controller in [
      _title,
      _description,
      _place,
      _longitude,
      _latitude,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  void _changed(String _) => _key = newIdempotencyKey();

  String? _required(String? value) =>
      value == null || value.trim().isEmpty ? 'Campo obrigatório.' : null;
  String? _coordinate(String? value, double bound) {
    final number = double.tryParse(value ?? '');
    return number == null || !number.isFinite || number.abs() > bound
        ? 'Coordenada inválida.'
        : null;
  }

  Future<void> _date() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _starts,
      firstDate: DateTime(1),
      lastDate: DateTime(9999, 12, 31),
      helpText: 'Data do encontro',
    );
    if (!mounted || date == null) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_starts),
      helpText: 'Hora local',
    );
    if (!mounted || time == null) return;
    setState(() {
      _starts = DateTime(
        date.year,
        date.month,
        date.day,
        time.hour,
        time.minute,
      );
      _key = newIdempotencyKey();
    });
  }

  Future<void> _save() async {
    if (_busy || !_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final values = <String, Object?>{
      'title': _title.text.trim(),
      'description': _description.text.trim().isEmpty
          ? null
          : _description.text.trim(),
      'location_label': _place.text.trim(),
      'longitude': double.parse(_longitude.text),
      'latitude': double.parse(_latitude.text),
      'category_code': _category,
      'starts_at': _starts.toUtc().toIso8601String(),
      'timezone': 'UTC',
      'visibility': _visibility,
    };
    try {
      final previous = widget.previous;
      final saved = previous == null
          ? await widget.repository.create(values, _key)
          : await widget.repository.update(previous, values);
      if (mounted) Navigator.of(context).pop(saved);
    } on ApiFailure catch (error) {
      if (mounted) setState(() => _error = error.message);
    } on Exception {
      if (mounted) {
        setState(() => _error = 'Não foi possível salvar o encontro.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(
        widget.previous == null ? 'Criar encontro' : 'Editar encontro',
      ),
    ),
    body: Form(
      key: _form,
      child: AbsorbPointer(
        absorbing: _busy,
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            TextFormField(
              controller: _title,
              maxLength: 120,
              validator: _required,
              onChanged: _changed,
              decoration: const InputDecoration(labelText: 'Título'),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _category,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Categoria'),
              items: const ['street', 'jdm', 'premium', 'drift']
                  .map(
                    (category) => DropdownMenuItem(
                      value: category,
                      child: Text(category.toUpperCase()),
                    ),
                  )
                  .toList(),
              onChanged: (value) => setState(() {
                _category = value!;
                _changed(value);
              }),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _visibility,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Visibilidade'),
              items: const [
                DropdownMenuItem(
                  value: 'listed',
                  child: Text('Listado para pessoas autenticadas'),
                ),
                DropdownMenuItem(
                  value: 'owner_only',
                  child: Text('Privado: somente eu'),
                ),
              ],
              onChanged: (value) => setState(() {
                _visibility = value!;
                _changed(value);
              }),
            ),
            const SizedBox(height: 16),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.schedule),
              title: const Text('Data e hora local'),
              subtitle: Text(_starts.toString().substring(0, 16)),
              trailing: const Icon(Icons.edit_calendar),
              onTap: _date,
            ),
            const Text(
              'O instante é armazenado em UTC. Datas passadas continuam permitidas.',
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _place,
              maxLength: 200,
              validator: _required,
              onChanged: _changed,
              decoration: const InputDecoration(labelText: 'Nome do local'),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _longitude,
              validator: (value) => _coordinate(value, 180),
              onChanged: _changed,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
                signed: true,
              ),
              decoration: const InputDecoration(labelText: 'Longitude'),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _latitude,
              validator: (value) => _coordinate(value, 90),
              onChanged: _changed,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
                signed: true,
              ),
              decoration: const InputDecoration(labelText: 'Latitude'),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _description,
              maxLength: 2000,
              maxLines: 4,
              onChanged: _changed,
              decoration: const InputDecoration(
                labelText: 'Descrição (opcional)',
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 16),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: _busy ? null : _save,
              icon: _busy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.check),
              label: const Text('Salvar encontro'),
            ),
          ],
        ),
      ),
    ),
  );
}
