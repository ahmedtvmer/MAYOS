import 'package:flutter/material.dart';

/// Reserved for the coach console (#23). Route access is capability-gated by the
/// router; this placeholder keeps the boundary without shipping coach features.
class CoachPlaceholderScreen extends StatelessWidget {
  const CoachPlaceholderScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Coach')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'The coach console arrives in a later release.',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
