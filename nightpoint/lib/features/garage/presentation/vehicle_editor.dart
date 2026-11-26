import 'dart:convert';
import 'package:flutter/material.dart';
import '../../../core/api/api_client.dart';
import '../../../core/api/idempotency_key.dart';
import '../data/garage_repository.dart';

class VehicleEditor extends StatefulWidget {
  const VehicleEditor({super.key, required this.repository, this.previous});
  final GarageRepository repository;
  final VehicleRecord? previous;
  @override
  State<VehicleEditor> createState() => _VehicleEditorState();
}

class _VehicleEditorState extends State<VehicleEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _brand, _model, _year, _color;
  late String _category;
  late bool _primary;
  bool _busy = false;
  String? _error, _key, _fingerprint;

  @override
  void initState() {
    super.initState();
    final vehicle = widget.previous;
    _brand = TextEditingController(text: vehicle?.brand);
    _model = TextEditingController(text: vehicle?.model);
    _year = TextEditingController(text: vehicle?.year?.toString());
    _color = TextEditingController(text: vehicle?.color);
    _category = vehicle?.category ?? 'car';
    _primary = vehicle?.primary ?? false;
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final values = <String, Object?>{
      'brand': _brand.text.trim(),
      'model': _model.text.trim(),
      'year': int.tryParse(_year.text),
      'color': _color.text.trim().isEmpty ? null : _color.text.trim(),
      'category': _category,
      'primary': _primary,
      'archived': widget.previous?.archived ?? false,
    };
    final fingerprint = jsonEncode(values);
    if (_fingerprint != fingerprint) {
      _key = newIdempotencyKey();
      _fingerprint = fingerprint;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final previous = widget.previous;
      final saved = previous == null
          ? await widget.repository.create(values, _key!)
          : await widget.repository.update(previous, values);
      if (mounted) Navigator.pop(context, saved);
    } on ApiFailure catch (failure) {
      if (mounted) setState(() => _error = failure.message);
    } on Exception {
      if (mounted) {
        setState(() => _error = 'Não foi possível salvar o veículo.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _brand.dispose();
    _model.dispose();
    _year.dispose();
    _color.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(
        widget.previous == null ? 'Adicionar veículo' : 'Editar veículo',
      ),
    ),
    body: Form(
      key: _form,
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text(
            'Sua garagem é privada. Use dados fictícios nesta demonstração.',
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _brand,
            enabled: !_busy,
            maxLength: 80,
            decoration: const InputDecoration(labelText: 'Marca'),
            validator: (v) =>
                v == null || v.trim().isEmpty ? 'Informe a marca' : null,
          ),
          TextFormField(
            controller: _model,
            enabled: !_busy,
            maxLength: 120,
            decoration: const InputDecoration(labelText: 'Modelo'),
            validator: (v) =>
                v == null || v.trim().isEmpty ? 'Informe o modelo' : null,
          ),
          TextFormField(
            controller: _year,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Ano (opcional)'),
            validator: (v) {
              if (v == null || v.isEmpty) return null;
              final year = int.tryParse(v);
              return year == null || year < 1900 || year > 2100
                  ? 'Ano entre 1900 e 2100'
                  : null;
            },
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _color,
            enabled: !_busy,
            maxLength: 60,
            decoration: const InputDecoration(labelText: 'Cor (opcional)'),
          ),
          DropdownButtonFormField<String>(
            initialValue: _category,
            decoration: const InputDecoration(labelText: 'Categoria'),
            items: const [
              DropdownMenuItem(value: 'car', child: Text('Carro')),
              DropdownMenuItem(value: 'motorcycle', child: Text('Moto')),
              DropdownMenuItem(value: 'truck', child: Text('Caminhão')),
              DropdownMenuItem(value: 'other', child: Text('Outro')),
            ],
            onChanged: _busy
                ? null
                : (v) {
                    if (v != null) setState(() => _category = v);
                  },
          ),
          SwitchListTile(
            title: const Text('Veículo principal'),
            subtitle: const Text('Opcional. Substitui o principal atual.'),
            value: _primary,
            onChanged: _busy || widget.previous?.archived == true
                ? null
                : (v) => setState(() => _primary = v),
          ),
          if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(_busy ? 'Salvando...' : 'Salvar veículo'),
          ),
        ],
      ),
    ),
  );
}
